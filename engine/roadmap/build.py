"""Builds the roadmap: portfolio -> jobs (packages + Wave 0 foundations) -> schedule -> waves, economics, unlocks."""

from __future__ import annotations

import math

from analyzer.schema import AnalysisResult
from engine.config import Strategy
from engine.roadmap import deps as deps_mod
from engine.roadmap.config import RoadmapConfig
from engine.roadmap.economics import build_economics
from engine.roadmap.headlines import build_headlines
from engine.roadmap.portfolio import build_selection
from engine.roadmap.scheduler import Job, Placement, duration_months, monthly_spend, schedule
from engine.roadmap.schema import (
    CutoverEvent,
    Item,
    ReasonCode,
    Roadmap,
    RoadmapMeta,
    Unscheduled,
    Wave,
)
from engine.roadmap.unlocks import evaluate
from engine.scenario import ClientScenario
from engine.schema import Recommendation, StrategyOption, WorkPackageReport

NOTES = [
    "ILLUSTRATIVE ASSUMPTIONS and a FICTIONAL client: every rate, capacity, foundation estimate and unlock mapping is configuration.",
    "Portfolio: the best feasible option per package under the budget, maximising the sum of priority-weighted scores (exact DP).",
    ("Sequencing: leaves first (a package starts after the packages it references have finished); entangled packages start together "
     "or, if too big for the capacity, are staggered with cutover held until the whole group is built."),
    "Wave = 1 + dependency depth among package groups. Wave 0 is foundations; the final wave lists opportunities, not work.",
    "Savings start the month after a package's last cutover event; migration and foundation spend are spread evenly over months.",
]


def _opt(w: WorkPackageReport, s: Strategy) -> StrategyOption:
    return next(o for o in w.options if o.strategy == s)


def _foundation(job_id: str, name: str, days: float, people: int, rate: float, wdpm: float, formula: str, for_pkgs: list[str]) -> Job:
    return Job(id=job_id, kind="foundation", name=name, people=people, effort_days=round(days, 4), cost=round(days * rate),
               duration=duration_months(days, people, wdpm), formula=formula,
               codes=[ReasonCode(code="FOUNDATION_FOR", detail=", ".join(sorted(for_pkgs)) or "-")])


def build_jobs(rec: Recommendation, strategy_by_pkg: dict[str, Strategy], edges: dict[str, set[str]], rcfg: RoadmapConfig) -> list[Job]:
    cfg = rec.assumptions["config"]
    rate, wdpm, cap = float(cfg["daily_rate_jpy"]), float(cfg["working_days_per_month"]), rcfg.capacity
    f, fp = rcfg.foundations, min(rcfg.foundations.team_people, rcfg.capacity)
    chosen = {p: s for p, s in strategy_by_pkg.items() if s != "retain"}
    jobs: list[Job] = []
    safety_jobs: dict[str, Job] = {}
    for pid, s in sorted(chosen.items()):
        w, o = rec.work_packages[pid], _opt(rec.work_packages[pid], s)
        gap = next(c.normalized for c in w.health.components if c.key == "test_evidence")
        effort, cost = o.effort_days or 0.0, o.migration_cost_jpy or 0
        if s in ("refactor", "rearchitect") and gap >= f.weak_test_gap:
            line = next((x for x in o.effort_lines if x.label == "Build safety-net tests first"), None)
            days = line.days if line else round(w.kloc * float(cfg["safety_net_days_per_kloc"]) * o.multipliers["uncertainty_buffer"], 4)
            if line:  # the line is already inside this package's cost: move it to Wave 0
                effort, cost = effort - days, cost - round(days * rate)
            safety_jobs[pid] = _foundation(
                f"foundation/safety-net/{pid}", f"Safety-net test suite: {w.name}", days, fp, rate, wdpm,
                f"KLOC {w.kloc:.3f} x {cfg['safety_net_days_per_kloc']:g} days/KLOC x uncertainty buffer "
                f"{o.multipliers['uncertainty_buffer']:g} (test gap {gap:.2f} >= {f.weak_test_gap:g})", [pid])
        people = max(1, min(round(o.team_size or 1), cap))
        risk = o.risk_score or 0.0
        needs = [name for name, strategies in f.required_by.items() if s in strategies]
        jobs.append(Job(
            id=pid, kind="package", name=w.name, people=people, effort_days=round(effort, 4), cost=cost,
            duration=duration_months(effort, people, wdpm), package_id=pid, module=w.module, strategy=s,
            quick=(risk <= rcfg.quick_win.max_risk and (o.duration_months or 0) <= rcfg.quick_win.max_months and not needs
                   and pid not in safety_jobs),
            value_per_risk=round((o.value.value if o.value else 0.0) / max(risk, 1.0), 6),
            cutover=(o.cutover_approach or "none", o.cutover_events or 0, o.cutover_hours_per_event or 0.0)))
    users = {name: [j for j in jobs if j.strategy in strategies] for name, strategies in f.required_by.items()}
    foundations: dict[str, Job] = {}
    if users["cicd"]:
        n = len(users["cicd"])
        foundations["cicd"] = _foundation("foundation/cicd", "CI/CD pipeline and automated builds", f.cicd.base_days + f.cicd.days_per_package * n, fp,
                                          rate, wdpm, f"{f.cicd.base_days:g} + {f.cicd.days_per_package:g} days x {n} packages that change code",
                                          [j.id for j in users["cicd"]])
    if users["observability"]:
        kloc = sum(rec.work_packages[j.id].kloc for j in users["observability"])
        foundations["observability"] = _foundation(
            "foundation/observability", "Observability: logging, metrics, tracing", f.observability.base_days + f.observability.days_per_kloc * kloc,
            fp, rate, wdpm, f"{f.observability.base_days:g} + {f.observability.days_per_kloc:g} days x {kloc:.3f} KLOC of the packages that need it",
            [j.id for j in users["observability"]])
    if users["facade"]:
        n = len(users["facade"])
        foundations["facade"] = _foundation("foundation/facade", "API facade for strangler cutover", f.facade.base_days + f.facade.days_per_package * n,
                                            fp, rate, wdpm, f"{f.facade.base_days:g} + {f.facade.days_per_package:g} days x {n} strangler packages",
                                            [j.id for j in users["facade"]])
    item_deps = deps_mod.item_dependencies(edges, set(chosen))
    groups = deps_mod.entangled_groups(item_deps)
    group_of = {m: i for i, g in enumerate(groups) for m in g}
    for j in jobs:
        j.group = f"G{group_of[j.id]}"
        peers = [m for m in groups[group_of[j.id]] if m != j.id]
        j.deps = set(item_deps[j.id]) - set(peers)  # entangled peers are handled together, not in sequence
        if j.deps:
            j.codes.append(ReasonCode(code="DEPENDS_ON", detail=", ".join(sorted(j.deps))))
        if peers:
            j.codes.append(ReasonCode(code="ENTANGLED_WITH", detail=", ".join(peers)))
        for name, strategies in f.required_by.items():
            if j.strategy in strategies and name in foundations:
                j.deps.add(foundations[name].id)
                j.codes.append(ReasonCode(code={"cicd": "NEEDS_CICD", "observability": "NEEDS_OBSERVABILITY", "facade": "NEEDS_FACADE"}[name],
                                          detail=foundations[name].id))
        if j.id in safety_jobs:
            j.deps.add(safety_jobs[j.id].id)
            j.codes.append(ReasonCode(code="NEEDS_SAFETY_NET", detail=safety_jobs[j.id].id))
        j.codes.append(ReasonCode(code="QUICK_WIN", detail=f"low risk, short, no foundations needed; value per risk {j.value_per_risk:g}") if j.quick else
                       ReasonCode(code="VALUE_PER_RISK_ORDER", detail=f"ordered by value per risk ({j.value_per_risk:g})"))
    return sorted(foundations.values(), key=lambda x: x.id) + sorted(safety_jobs.values(), key=lambda x: x.id) + jobs


def _cutover_months(job: Job, p: Placement, group_end: int | None) -> list[CutoverEvent]:
    approach, events, hours = job.cutover
    if events == 0:
        return []
    if group_end is not None:  # entangled group built in stages: cut over only once everything is built
        return [CutoverEvent(month=group_end, hours=hours) for _ in range(events)]
    if approach == "big_bang":
        return [CutoverEvent(month=p.end, hours=hours)]
    return [CutoverEvent(month=min(p.end, p.start + math.ceil(i * job.duration / events) - 1), hours=hours) for i in range(1, events + 1)]


def build_roadmap(rec: Recommendation, analysis: AnalysisResult, scenario: ClientScenario, rcfg: RoadmapConfig,
                  profile: str | None = None) -> Roadmap:
    profile = profile or rec.meta.selected_profile
    selection, strategy_by_pkg = build_selection(rec, profile, scenario.constraints.budget_ceiling_jpy)
    edges = deps_mod.package_edges(rec, analysis)
    jobs = build_jobs(rec, strategy_by_pkg, edges, rcfg)
    by_id = {j.id: j for j in jobs}
    pkg_groups: dict[str, list[str]] = {}
    for j in jobs:
        if j.kind == "package":
            pkg_groups.setdefault(j.group, []).append(j.id)
    groups = [[j.id] for j in jobs if j.kind == "foundation"] + [sorted(g) for _, g in sorted(pkg_groups.items())]
    placed, failed = schedule(jobs, groups, rcfg.capacity, rcfg.yearly_budget_cap_jpy, rcfg.search_horizon_months)

    # waves: 1 + depth among package groups (foundations are wave 0)
    group_of = {j.id: j.group for j in jobs if j.kind == "package"}
    group_deps = {g: {group_of[d] for m in ms for d in by_id[m].deps if d in group_of and group_of[d] != g} for g, ms in pkg_groups.items()}
    depth: dict[str, int] = {}

    def level(g: str) -> int:
        if g not in depth:
            depth[g] = 1 + max((level(d) for d in group_deps[g]), default=0)
        return depth[g]

    staggered = {j.group for j in jobs if j.id in placed and any(c.code == "ENTANGLED_STAGGERED" for c in placed[j.id].extra_codes)}
    group_end = {g: max(placed[m].end for m in ms if m in placed) for g, ms in pkg_groups.items() if any(m in placed for m in ms)}
    items: list[Item] = []
    for j in sorted(jobs, key=lambda x: (placed[x.id].start if x.id in placed else 10**9, x.id)):
        if j.id not in placed:
            continue
        p = placed[j.id]
        sync = group_end[j.group] if j.kind == "package" and j.group in staggered else None
        events = _cutover_months(j, p, sync) if j.kind == "package" else []
        codes = j.codes + p.extra_codes + ([ReasonCode(code="CUTOVER_AFTER_ENTANGLED_GROUP", detail=f"cutover held to month {sync}")] if sync else [])
        items.append(Item(
            id=j.id, wave=0 if j.kind == "foundation" else level(j.group), kind=j.kind, name=j.name, package_id=j.package_id,  # type: ignore[arg-type]
            module=j.module, strategy=j.strategy, start_month=p.start, end_month=p.end, people=j.people, lane=0, team="",  # type: ignore[arg-type]
            effort_days=j.effort_days, cost_jpy=j.cost, monthly_spend_jpy=monthly_spend(j.cost, j.duration), cutover_events=events,
            depends_on=sorted(j.deps), reason_codes=codes, formula=j.formula))
    lanes: list[int] = []  # end month of the last item in each display lane
    for it in sorted(items, key=lambda x: (x.start_month, x.id)):
        lane = next((i for i, e in enumerate(lanes) if e < it.start_month), len(lanes))
        lanes[lane:lane + 1] = [it.end_month]
        it.lane, it.team = lane + 1, f"Team {lane + 1}"
    completion = {it.package_id: max([it.end_month] + [e.month for e in it.cutover_events]) for it in items if it.package_id}
    completion_all: dict[str, int | None] = {pid: completion.get(pid) for pid in strategy_by_pkg if strategy_by_pkg[pid] != "retain"}
    last_wave = max([it.wave for it in items], default=0)
    waves = []
    for n in range(last_wave + 1):
        members = [it for it in items if it.wave == n]
        if not members and n:
            continue
        peak = max((sum(i.people for i in members if i.start_month <= m <= i.end_month) for m in range(1, max((i.end_month for i in members), default=0) + 1)), default=0)
        waves.append(Wave(number=n, name="Wave 0: Foundations" if n == 0 else rcfg.wave_name_template.format(n=n),
                          start_month=min((i.start_month for i in members), default=None), end_month=max((i.end_month for i in members), default=None),
                          item_ids=sorted(i.id for i in members), cost_jpy=sum(i.cost_jpy for i in members), peak_people=peak))
    waves.append(Wave(number=last_wave + 1, name="What modernization unlocks", start_month=None, end_month=None, item_ids=[], cost_jpy=0, peak_people=0))
    unlocks = evaluate(rec, strategy_by_pkg, completion_all, rcfg)
    econ = build_economics(rec, items, strategy_by_pkg, completion_all, scenario, rec.assumptions["config"]["tco"]["discount_rate"])
    finish = max(completion.values(), default=None)
    return Roadmap(
        meta=RoadmapMeta(analysis_name=rec.meta.analysis_name, profile=profile, scenario_client=rec.meta.scenario_client,
                         capacity_people=rcfg.capacity, teams=rcfg.teams, yearly_budget_cap_jpy=rcfg.yearly_budget_cap_jpy,
                         finish_month=finish, notes=NOTES),
        portfolio=selection, waves=waves, items=sorted(items, key=lambda i: (i.wave, i.start_month, i.id)),
        unscheduled=[Unscheduled(id=i, name=by_id[i].name, reason_codes=c) for i, c in sorted(failed.items())],
        retained_packages=sorted(p for p, s in strategy_by_pkg.items() if s == "retain"), unlocks=unlocks, economics=econ,
        headlines=build_headlines(rec, analysis, selection, items, econ, unlocks, finish),
        assumptions={"illustrative": True, "roadmap": rcfg.model_dump(mode="json")})
