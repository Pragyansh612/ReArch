"""Phase 4 tests: exact portfolio selection, dependency/capacity/budget-respecting waves, economics, determinism."""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest

from analyzer.analyze import analyze
from analyzer.schema import AnalysisResult
from engine.config import EngineConfig, Strategy
from engine.recommend import recommend
from engine.roadmap.__main__ import main as cli_main
from engine.roadmap.build import build_roadmap
from engine.roadmap.config import RoadmapConfig, Unlock
from engine.roadmap.portfolio import Opt, package_options, package_weights, select
from engine.roadmap.schema import Item, Roadmap
from engine.scenario import ClientScenario
from engine.schema import Recommendation
from engine.tests.conftest import FIXTURE

KNOWN_CODES = {"DEPENDS_ON", "ENTANGLED_WITH", "ENTANGLED_STAGGERED", "CUTOVER_AFTER_ENTANGLED_GROUP", "NEEDS_SAFETY_NET", "NEEDS_CICD",
               "NEEDS_OBSERVABILITY", "NEEDS_FACADE", "CAPACITY", "BUDGET_CAP", "QUICK_WIN", "VALUE_PER_RISK_ORDER", "FOUNDATION_FOR"}


def make(rec: Recommendation, analysis: AnalysisResult, scenario: ClientScenario, rcfg: RoadmapConfig, profile: str) -> Roadmap:
    return build_roadmap(rec, analysis, scenario, rcfg, profile)


@pytest.fixture(scope="session")
def ltv(tight_rec: Recommendation, analysis: AnalysisResult, tight_scenario: ClientScenario, rcfg: RoadmapConfig) -> Roadmap:
    return make(tight_rec, analysis, tight_scenario, rcfg, "long_term_value")


@pytest.fixture(scope="session")
def client(rec: Recommendation, analysis: AnalysisResult, scenario: ClientScenario, rcfg: RoadmapConfig) -> Roadmap:
    return make(rec, analysis, scenario, rcfg, "client_scenario")


def packages(rm: Roadmap) -> list[Item]:
    return [i for i in rm.items if i.kind == "package"]


def people_by_month(items: list[Item]) -> dict[int, int]:
    out: dict[int, int] = {}
    for i in items:
        for m in range(i.start_month, i.end_month + 1):
            out[m] = out.get(m, 0) + i.people
    return out


# --- portfolio ----------------------------------------------------------------------------------------------------------------

def _brute_force(options: dict, budget: int, order: dict, weights: dict) -> tuple[int, int, tuple]:  # type: ignore[type-arg]
    ids = sorted(options)
    best = None
    for combo in itertools.product(*(options[p] for p in ids)):
        cost = sum(o.cost for o in combo)
        if cost > budget:
            continue
        key = (-sum(weights[p] * o.score_int for p, o in zip(ids, combo, strict=True)), cost, tuple(order[o.strategy] for o in combo))
        if best is None or key < best:
            best = key
    assert best is not None
    return -best[0], best[1], best[2]


@pytest.mark.parametrize("budget", [0, 1_000_000, 5_000_000, 10_000_000, 19_200_000, 20_000_000, 22_616_080, 10**12])
def test_the_optimiser_matches_brute_force_on_the_fixture(rec: Recommendation, cfg: EngineConfig, budget: int) -> None:
    options = package_options(rec, "long_term_value")
    order = {s: i for i, s in enumerate(cfg.strategies)}
    weights = package_weights(rec)
    chosen = select(options, budget, order, weights)
    ids = sorted(options)
    got = (sum(weights[p] * chosen[p].score_int for p in ids), sum(chosen[p].cost for p in ids), tuple(order[chosen[p].strategy] for p in ids))
    assert got == _brute_force(options, budget, order, weights)  # same objective, same cost and the same tie-breaking
    assert got[1] <= budget


def test_a_non_binding_budget_leaves_the_portfolio_unchanged(client: Roadmap) -> None:
    p = client.portfolio
    assert not p.budget_binding and p.downgrades == []
    assert p.constrained == p.unconstrained


def test_a_binding_budget_downgrades_exactly_the_packages_that_changed(ltv: Roadmap, tight_scenario: ClientScenario) -> None:
    p = ltv.portfolio
    assert p.budget_binding and p.budget_ceiling_jpy == 20_000_000
    assert p.unconstrained.total_migration_cost_jpy > 20_000_000 >= p.constrained.total_migration_cost_jpy
    assert p.constrained.total_score <= p.unconstrained.total_score
    before = {c.package_id: c.strategy for c in p.unconstrained.choices}
    after = {c.package_id: c.strategy for c in p.constrained.choices}
    assert {d.package_id for d in p.downgrades} == {k for k in before if before[k] != after[k]} and p.downgrades
    for d in p.downgrades:
        assert (d.unconstrained, d.constrained) == (before[d.package_id], after[d.package_id])
        assert d.score_lost >= 0 and "budget" in d.reason
    assert p.method.startswith("exact")


def test_portfolio_totals_match_their_choices(ltv: Roadmap) -> None:
    for pf in (ltv.portfolio.unconstrained, ltv.portfolio.constrained):
        assert pf.total_migration_cost_jpy == sum(c.migration_cost_jpy for c in pf.choices)
        assert sum(c.weight for c in pf.choices) == pytest.approx(1.0, abs=1e-5)
        assert pf.total_score == pytest.approx(sum(c.weight * c.score for c in pf.choices), abs=1e-3)  # weighted mean, 0-100
        assert pf.total_unweighted_score == pytest.approx(sum(c.score for c in pf.choices), abs=1e-4)
        assert sum(pf.strategy_mix.values()) == len(pf.choices)


def test_package_weights_are_each_packages_share_of_the_estate_do_nothing_cost(rec: Recommendation, ltv: Roadmap) -> None:
    weights = package_weights(rec)
    for wid, w in rec.work_packages.items():
        retain = next(o for o in w.options if o.strategy == "retain")
        assert retain.tco is not None and weights[wid] == retain.tco.tco_jpy
    total = sum(weights.values())
    for c in ltv.portfolio.constrained.choices:  # the roadmap's weights are those shares
        assert c.weight == pytest.approx(weights[c.package_id] / total, abs=1e-6)
    big, small = max(weights, key=lambda k: weights[k]), min(weights, key=lambda k: weights[k])
    assert weights[big] > weights[small]


def test_two_otherwise_identical_packages_of_different_size_get_proportionally_different_weight() -> None:
    options = {"big": [Opt("retain", 50_000, 0), Opt("rehost", 80_000, 10)],
               "small": [Opt("retain", 50_000, 0), Opt("rehost", 80_000, 10)]}  # identical options, scores and costs
    order: dict[Strategy, int] = {"retain": 0, "rehost": 1}
    weights = {"big": 3_000_000, "small": 1_000_000}  # the big package carries 3x the do-nothing cost
    assert weights["big"] / weights["small"] == 3
    chosen = select(options, 10, order, weights)  # budget for exactly one upgrade
    assert chosen["big"].strategy == "rehost" and chosen["small"].strategy == "retain"  # spend goes to the larger value at stake
    assert select(options, 10, order, {"big": 1_000_000, "small": 3_000_000})["small"].strategy == "rehost"
    assert select(options, 10, order)["big"].strategy == "retain"  # unweighted: a tie, broken by the fixed rule
    assert select(options, 20, order, weights)["big"].strategy == select(options, 20, order, weights)["small"].strategy == "rehost"


def test_the_objective_is_weighted_in_proportion_to_value_at_stake(rec: Recommendation, cfg: EngineConfig) -> None:
    """Scaling one package's value at stake changes the objective by exactly that factor for that package."""
    options = package_options(rec, "long_term_value")
    weights = package_weights(rec)
    order = {s: i for i, s in enumerate(cfg.strategies)}
    base = select(options, 10**12, order, weights)
    pid = max(weights, key=lambda k: weights[k])
    objective = sum(weights[p] * o.score_int for p, o in base.items())
    heavier = {**weights, pid: weights[pid] * 4}
    again = select(options, 10**12, order, heavier)
    assert sum(heavier[p] * o.score_int for p, o in again.items()) == objective + 3 * weights[pid] * base[pid].score_int


def test_scheduled_strategies_are_the_constrained_portfolio(ltv: Roadmap) -> None:
    chosen = {c.package_id: c.strategy for c in ltv.portfolio.constrained.choices}
    scheduled = {i.package_id: i.strategy for i in packages(ltv)}
    assert scheduled == {p: s for p, s in chosen.items() if s != "retain"}
    assert set(ltv.retained_packages) == {p for p, s in chosen.items() if s == "retain"}
    assert ltv.unscheduled == []


# --- sequencing ---------------------------------------------------------------------------------------------------------------

def _entangled(rm: Roadmap, rec: Recommendation, analysis: AnalysisResult) -> tuple[dict[str, set[str]], list[set[str]]]:
    """Independent re-derivation: package dependencies (through retained packages) and mutual-dependency groups."""
    owner = {c: w.id for w in rec.work_packages.values() for c in w.classes}
    edges: dict[str, set[str]] = {w: set() for w in rec.work_packages}
    for w in rec.work_packages.values():
        for c in w.classes:
            edges[w.id] |= {owner[d] for d in analysis.classes[c].depends_on if owner[d] != w.id}
    items = {i.package_id for i in packages(rm) if i.package_id}
    deps: dict[str, set[str]] = {}
    for a in items:
        found, seen, stack = set(), {a}, list(edges[a])
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            found.add(n) if n in items else stack.extend(edges[n])
        deps[a] = found - {a}
    reach: dict[str, set[str]] = {}
    for a, direct in deps.items():  # transitive closure over the item graph: mutual reachability = entangled
        seen, stack = set(), list(direct)
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack.extend(deps[n])
        reach[a] = seen
    groups = [{a} | {b for b in reach[a] if a in reach[b]} for a in sorted(deps)]
    return deps, groups


@pytest.mark.parametrize("which", ["client", "ltv"])
def test_dependency_order_is_respected(which: str, request: pytest.FixtureRequest, rec: Recommendation, tight_rec: Recommendation,
                                       analysis: AnalysisResult) -> None:
    rm: Roadmap = request.getfixturevalue(which)
    deps, groups = _entangled(rm, tight_rec if which == "ltv" else rec, analysis)
    by_pkg = {i.package_id: i for i in packages(rm)}
    checked = 0
    for a, ds in deps.items():
        peers = next(g for g in groups if a in g)
        for b in ds - peers:
            assert by_pkg[b].end_month < by_pkg[a].start_month, (b, a)  # leaves first: finish what you depend on
            assert b in by_pkg[a].depends_on and by_pkg[b].wave < by_pkg[a].wave
            checked += 1
        if len(peers) > 1:  # entangled: started together, or staggered with cutover held until the whole group is built
            starts = {by_pkg[p].start_month for p in peers}
            staggered = any(c.code == "ENTANGLED_STAGGERED" for c in by_pkg[a].reason_codes)
            assert len(starts) == 1 or staggered
            assert any(c.code == "ENTANGLED_WITH" for c in by_pkg[a].reason_codes)
    assert checked > 0


def test_foundations_precede_the_packages_that_need_them(ltv: Roadmap, rcfg: RoadmapConfig) -> None:
    found = {i.id: i for i in ltv.items if i.kind == "foundation"}
    assert {"foundation/cicd", "foundation/observability", "foundation/facade"} <= set(found)
    for i in packages(ltv):
        needs = {c.detail for c in i.reason_codes if c.code.startswith("NEEDS_")}
        expected = {f"foundation/{n}" for n, strategies in rcfg.foundations.required_by.items() if i.strategy in strategies}
        assert expected <= needs
        for n in needs:
            assert found[n].end_month < i.start_month, (n, i.id)
            assert n in i.depends_on
    assert all(f.wave == 0 for f in found.values())
    assert min(i.wave for i in packages(ltv)) == 1


def test_weak_test_packages_get_a_safety_net_suite_before_they_change(ltv: Roadmap, tight_rec: Recommendation, rcfg: RoadmapConfig) -> None:
    safety = {i.id.split("/", 2)[2]: i for i in ltv.items if i.id.startswith("foundation/safety-net/")}
    assert safety
    for i in packages(ltv):
        w = tight_rec.work_packages[i.package_id or ""]
        gap = next(c.normalized for c in w.health.components if c.key == "test_evidence")
        needs = i.strategy in ("refactor", "rearchitect") and gap >= rcfg.foundations.weak_test_gap
        assert (i.package_id in safety) == needs
        if needs:
            assert safety[i.package_id or ""].end_month < i.start_month
    assert not [i for i in packages(ltv) if i.strategy in ("rehost", "replatform") and i.package_id in safety]


def test_no_facade_or_pipeline_when_nothing_needs_them(client: Roadmap) -> None:
    assert [i for i in client.items if i.kind == "foundation"] == []  # an all-rehost programme needs no foundations
    assert client.waves[0].number == 0 and client.waves[0].item_ids == []


def test_foundation_estimates_follow_their_formulas(ltv: Roadmap, tight_rec: Recommendation, rcfg: RoadmapConfig) -> None:
    f, rate = rcfg.foundations, tight_rec.assumptions["config"]["daily_rate_jpy"]
    wdpm = tight_rec.assumptions["config"]["working_days_per_month"]
    cicd = next(i for i in ltv.items if i.id == "foundation/cicd")
    n = len([i for i in packages(ltv) if i.strategy in f.required_by["cicd"]])
    assert cicd.effort_days == round(f.cicd.base_days + f.cicd.days_per_package * n, 4)
    assert cicd.cost_jpy == round(cicd.effort_days * rate) and cicd.formula
    facade = next(i for i in ltv.items if i.id == "foundation/facade")
    assert facade.effort_days == round(f.facade.base_days + f.facade.days_per_package
                                       * len([i for i in packages(ltv) if i.strategy in f.required_by["facade"]]), 4)
    for i in ltv.items:
        assert i.end_month - i.start_month + 1 >= math.ceil(i.effort_days / (i.people * wdpm) - 1e-9) or i.kind == "package"
        assert i.cost_jpy == sum(i.monthly_spend_jpy)


@pytest.mark.parametrize("which", ["client", "ltv"])
def test_capacity_is_never_exceeded(which: str, request: pytest.FixtureRequest, rcfg: RoadmapConfig) -> None:
    rm: Roadmap = request.getfixturevalue(which)
    assert max(people_by_month(rm.items).values()) <= rcfg.capacity == rm.meta.capacity_people


def test_a_smaller_team_stretches_the_programme_but_still_respects_capacity(
        tight_rec: Recommendation, analysis: AnalysisResult, tight_scenario: ClientScenario, rcfg: RoadmapConfig, ltv: Roadmap) -> None:
    small = rcfg.model_copy(update={"teams": 1, "team_size_people": 4})
    rm = make(tight_rec, analysis, tight_scenario, small, "long_term_value")
    assert max(people_by_month(rm.items).values()) <= 4
    assert all(i.people <= 4 for i in rm.items)  # people needed are capped at the capacity
    assert (rm.meta.finish_month or 0) > (ltv.meta.finish_month or 0)
    assert rm.unscheduled == []


def test_a_yearly_budget_cap_is_never_exceeded_and_delays_work(
        tight_rec: Recommendation, analysis: AnalysisResult, tight_scenario: ClientScenario, rcfg: RoadmapConfig, ltv: Roadmap) -> None:
    year: dict[int, int] = {}
    for i in ltv.items:
        for k, s in enumerate(i.monthly_spend_jpy):
            year[(i.start_month + k - 1) // 12] = year.get((i.start_month + k - 1) // 12, 0) + s
    cap = round(max(year.values()) * 0.6)
    capped_cfg = rcfg.model_copy(update={"yearly_budget_cap_jpy": cap})
    rm = make(tight_rec, analysis, tight_scenario, capped_cfg, "long_term_value")
    spent: dict[int, int] = {}
    for i in rm.items:
        for k, s in enumerate(i.monthly_spend_jpy):
            spent[(i.start_month + k - 1) // 12] = spent.get((i.start_month + k - 1) // 12, 0) + s
    assert max(spent.values()) <= cap
    assert (rm.meta.finish_month or 0) >= (ltv.meta.finish_month or 0)
    assert any(c.code == "BUDGET_CAP" for i in rm.items for c in i.reason_codes)
    assert rm.meta.yearly_budget_cap_jpy == cap


def test_every_placement_has_at_least_one_reason_code(ltv: Roadmap, client: Roadmap) -> None:
    for rm in (ltv, client):
        for i in rm.items:
            assert i.reason_codes and {c.code for c in i.reason_codes} <= KNOWN_CODES
            assert all(c.detail for c in i.reason_codes)
            if i.kind == "foundation":
                assert any(c.code == "FOUNDATION_FOR" for c in i.reason_codes)
            else:
                assert any(c.code in ("QUICK_WIN", "VALUE_PER_RISK_ORDER") for c in i.reason_codes)


def test_quick_wins_start_first_and_need_no_foundations(ltv: Roadmap) -> None:
    quick = [i for i in packages(ltv) if any(c.code == "QUICK_WIN" for c in i.reason_codes)]
    assert quick and min(i.start_month for i in quick) == 1
    assert all(not any(c.code.startswith("NEEDS_") for c in i.reason_codes) for i in quick)
    assert all(i.strategy == "rehost" for i in quick)


# --- Gantt shape ----------------------------------------------------------------------------------------------------------------

def test_the_output_is_gantt_ready(ltv: Roadmap) -> None:
    lanes: dict[int, list[Item]] = {}
    for i in ltv.items:
        assert 1 <= i.start_month <= i.end_month and len(i.monthly_spend_jpy) == i.end_month - i.start_month + 1
        assert i.team == f"Team {i.lane}" and i.people >= 1 and i.wave >= 0
        lanes.setdefault(i.lane, []).append(i)
        assert i.kind == "foundation" or i.package_id
    for items in lanes.values():  # a lane is a display row: no overlaps inside it
        items.sort(key=lambda x: x.start_month)
        assert all(a.end_month < b.start_month for a, b in itertools.pairwise(items))
    waves = {w.number: w for w in ltv.waves}
    assert waves[0].name == "Wave 0: Foundations" and waves[max(waves)].name == "What modernization unlocks"
    assert waves[max(waves)].item_ids == []
    for n, w in waves.items():
        members = [i for i in ltv.items if i.wave == n]
        assert w.item_ids == sorted(i.id for i in members) and w.cost_jpy == sum(i.cost_jpy for i in members)
        assert w.peak_people <= ltv.meta.capacity_people
    assert ltv.meta.finish_month == max(max([i.end_month] + [e.month for e in i.cutover_events]) for i in packages(ltv))


def test_cutover_events_follow_the_cutover_approach(ltv: Roadmap, tight_rec: Recommendation) -> None:
    for i in packages(ltv):
        o = next(x for x in tight_rec.work_packages[i.package_id or ""].options if x.strategy == i.strategy)
        assert len(i.cutover_events) == o.cutover_events
        assert all(e.hours == o.cutover_hours_per_event for e in i.cutover_events)
        held = any(c.code == "CUTOVER_AFTER_ENTANGLED_GROUP" for c in i.reason_codes)
        for e in i.cutover_events:
            assert i.start_month <= e.month if not held else e.month >= i.end_month
            assert held or e.month <= i.end_month
        if o.cutover_approach == "big_bang" and not held:
            assert [e.month for e in i.cutover_events] == [i.end_month]


# --- economics -----------------------------------------------------------------------------------------------------------------

def test_economics_reconstruct_from_the_schedule(ltv: Roadmap, tight_rec: Recommendation, tight_scenario: ClientScenario) -> None:
    e = ltv.economics
    horizon = tight_scenario.constraints.planning_horizon_years * 12
    assert e.horizon_months == horizon and len(e.quarters) == horizon // 3
    spend = [0] * (horizon + 1)
    for i in ltv.items:
        for k, s in enumerate(i.monthly_spend_jpy):
            if i.start_month + k <= horizon:
                spend[i.start_month + k] += s
    assert e.total_programme_cost_jpy == sum(spend)
    chosen = {c.package_id: c.strategy for c in ltv.portfolio.constrained.choices}
    done = {i.package_id: max([i.end_month] + [c.month for c in i.cutover_events]) for i in packages(ltv)}
    retain_m, roadmap_m = [0.0] * (horizon + 1), [0.0] * (horizon + 1)
    for pid, w in tight_rec.work_packages.items():
        r = next(o for o in w.options if o.strategy == "retain").tco
        c = next(o for o in w.options if o.strategy == chosen[pid]).tco
        assert r is not None and c is not None
        before = r.baseline_maintenance_jpy_per_year + r.baseline_run_jpy_per_year + r.baseline_change_jpy_per_year
        after = c.steady_state_maintenance_jpy + c.steady_state_run_jpy + c.steady_state_change_jpy
        for m in range(1, horizon + 1):
            retain_m[m] += before / 12
            roadmap_m[m] += (after if pid in done and m > done[pid] else before) / 12
    cum_r = cum_p = npv = 0.0
    nets = []
    for m in range(1, horizon + 1):
        cum_r += retain_m[m]
        cum_p += roadmap_m[m] + spend[m]
        nets.append(cum_r - cum_p)
        npv += (retain_m[m] - roadmap_m[m] - spend[m]) / (1 + e.discount_rate) ** (m / 12)
        if m % 3 == 0:
            q = e.quarters[m // 3 - 1]
            assert (q.month_end, q.roadmap_cumulative_cost_jpy, q.retain_cumulative_cost_jpy, q.net_cumulative_jpy) == (
                m, round(cum_p), round(cum_r), round(cum_r - cum_p))
            assert q.net_cumulative_jpy == q.retain_cumulative_cost_jpy - q.roadmap_cumulative_cost_jpy or abs(
                q.net_cumulative_jpy - (q.retain_cumulative_cost_jpy - q.roadmap_cumulative_cost_jpy)) <= 1
            assert q.programme_spend_jpy == sum(spend[m - 2:m + 1])
    assert e.npv_vs_retain_jpy == round(npv)
    assert e.peak_investment_jpy == round(max(0.0, -min(nets)))
    assert e.payback_quarter is None or e.quarters[e.payback_quarter - 1].net_cumulative_jpy >= 0
    for q in e.quarters[: (e.payback_quarter or 0) - 1]:
        assert q.net_cumulative_jpy < 0 or q.quarter == 0  # not yet paid back before the payback quarter


def test_payback_quarter_is_the_first_return_to_zero_after_investing(client: Roadmap) -> None:
    e = client.economics
    assert e.total_programme_cost_jpy > 0 and e.payback_quarter is not None
    first_negative = next(q.quarter for q in e.quarters if q.net_cumulative_jpy < 0)
    assert e.payback_quarter > first_negative
    assert all(q.net_cumulative_jpy < 0 for q in e.quarters[first_negative - 1:e.payback_quarter - 1])
    assert e.quarters[e.payback_quarter - 1].net_cumulative_jpy >= 0 and e.npv_vs_retain_jpy > 0
    assert e.peak_investment_jpy >= max(-q.net_cumulative_jpy for q in e.quarters)  # monthly peak >= quarterly shortfall


def test_a_programme_that_saves_nothing_has_no_payback_and_a_negative_npv(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rcfg: RoadmapConfig) -> None:
    no_savings = cfg.model_copy(update={"tco": cfg.tco.model_copy(update={"maintenance_days_per_kloc_year": 0.0,
                                                                          "run_cost_jpy_per_kloc_year": 0.0})})
    quiet = scenario.model_copy(deep=True)
    quiet.change_requests_per_year = {}  # and no change requests: nothing left to save
    rec0 = recommend(analysis, cfg=no_savings, scenario=quiet, sensitivity=False)
    rm = make(rec0, analysis, quiet, rcfg, "long_term_value")
    e = rm.economics
    assert e.total_programme_cost_jpy > 0 and e.payback_quarter is None and e.npv_vs_retain_jpy < 0
    assert e.peak_investment_jpy > 0 and e.peak_investment_quarter is not None


def test_kpi_trajectory_only_for_what_the_model_supports(ltv: Roadmap, scenario: ClientScenario) -> None:
    by = {k.objective: k for k in ltv.economics.kpis}
    assert by["maintenance_cost"].modelled and by["run_cost"].modelled
    assert not by["change_lead_time"].modelled and by["change_lead_time"].points == [] and "not modelled" in by["change_lead_time"].note
    pts = [p.value for p in by["maintenance_cost"].points]
    assert pts[0] <= by["maintenance_cost"].current and pts == sorted(pts, reverse=True)  # only ever improves
    assert pts[-1] < by["maintenance_cost"].current


# --- unlocks --------------------------------------------------------------------------------------------------------------------

def test_unlocks_follow_the_modernized_packages(ltv: Roadmap, client: Roadmap, rcfg: RoadmapConfig) -> None:
    assert {u.id for u in ltv.unlocks} == {u.id for u in rcfg.unlocks}
    assert all(u.status in ("unlocked", "not_unlocked", "module_not_analysed") for u in ltv.unlocks)
    assert all(u.status != "unlocked" for u in client.unlocks)  # a rehost-only programme exposes no APIs
    assert {u.id: u.status for u in ltv.unlocks}["demand_forecasting"] == "module_not_analysed"  # fixture has no product module


def test_an_unlocked_opportunity_lists_its_prerequisites_and_a_start_month(
        tight_rec: Recommendation, analysis: AnalysisResult, tight_scenario: ClientScenario, rcfg: RoadmapConfig) -> None:
    custom = rcfg.model_copy(update={"unlocks": [Unlock.model_validate({
        "id": "order_apis", "name": "Order data platform", "kind": "data", "description": "order data via APIs",
        "requires": [{"module": "order", "min_strategy": "rehost", "min_loc_share": 0.5}]})]})
    rm = make(tight_rec, analysis, tight_scenario, custom, "long_term_value")
    u = rm.unlocks[0]
    order_pkgs = {i.package_id: i for i in packages(rm) if i.module == "order"}
    assert u.status == "unlocked" and u.prerequisite_packages and set(u.prerequisite_packages) <= set(order_pkgs)
    done = {p: max([order_pkgs[p].end_month] + [c.month for c in order_pkgs[p].cutover_events]) for p in u.prerequisite_packages}
    assert u.available_from_month == max(done.values()) + 1 and u.blocked_by == []
    strict = custom.model_copy(update={"unlocks": [Unlock.model_validate({
        "id": "x", "name": "x", "kind": "ai", "description": "x",
        "requires": [{"module": "order", "min_strategy": "rearchitect", "min_loc_share": 1.0}]})]})
    blocked = make(tight_rec, analysis, tight_scenario, strict, "long_term_value").unlocks[0]
    assert blocked.status == "not_unlocked" and blocked.blocked_by and blocked.available_from_month is None


# --- determinism, schema, CLI ----------------------------------------------------------------------------------------------------

def test_the_roadmap_is_deterministic(analysis: AnalysisResult, cfg: EngineConfig, tight_scenario: ClientScenario, rcfg: RoadmapConfig) -> None:
    dumps = []
    for _ in range(2):
        rec2 = recommend(analyze(FIXTURE, name="legacy-sample"), cfg=cfg, scenario=tight_scenario, sensitivity=False)
        dumps.append(make(rec2, analysis, tight_scenario, rcfg, "long_term_value").model_dump_json())
    assert dumps[0] == dumps[1]


def test_roadmap_roundtrips_through_the_schema(ltv: Roadmap) -> None:
    assert Roadmap.model_validate_json(ltv.model_dump_json()) == ltv
    assert ltv.assumptions["illustrative"] is True and any("FICTIONAL" in n for n in ltv.meta.notes)


def test_cli_writes_roadmap_json(tmp_path: Path) -> None:
    analysis_path = tmp_path / "legacy-sample.json"
    analysis_path.write_text(analyze(FIXTURE, name="legacy-sample").model_dump_json())
    assert cli_main([str(analysis_path), "--profile", "long_term_value", "--out", str(tmp_path)]) == 0
    out = json.loads((tmp_path / "legacy-sample.roadmap.json").read_text())
    assert out["meta"]["profile"] == "long_term_value" and out["items"] and out["waves"][-1]["name"] == "What modernization unlocks"
    assert cli_main([str(tmp_path / "missing.json")]) == 2
    assert cli_main([str(analysis_path), "--profile", "bogus", "--out", str(tmp_path)]) == 2


# --- headline findings ----------------------------------------------------------------------------------------------------------

def test_headlines_are_deterministic_sentences_built_from_the_numbers(client: Roadmap, rec: Recommendation, analysis: AnalysisResult) -> None:
    by = {h.id: h for h in client.headlines}
    assert list(by) == ["portfolio", "value", "largest_exposure", "rejected_option", "breakeven_question", "calibration", "unlocks",
                        "broken_references", "dependencies"]
    assert all(h.text.endswith(".") and h.kind for h in client.headlines)
    p = by["portfolio"]
    assert p.numbers["migration_cost_jpy"] == client.portfolio.constrained.total_migration_cost_jpy
    assert f"{client.portfolio.constrained.total_migration_cost_jpy / 1e6:,.1f} million" in p.text or p.numbers["migration_cost_jpy"] < 1e6
    v = by["value"]
    assert v.numbers["npv_vs_retain_jpy"] == client.economics.npv_vs_retain_jpy and v.numbers["peak_investment_jpy"] == client.economics.peak_investment_jpy
    assert (f"quarter {client.economics.payback_quarter}" in v.text) == (client.economics.payback_quarter is not None)
    broken = [f for f in analysis.findings if f.kind == "broken_reference"]
    assert by["broken_references"].numbers["count"] == len(broken) and str(len(broken)) in by["broken_references"].text
    d = rec.estate_findings
    assert by["dependencies"].numbers == {"outdated": d.outdated, "checked": d.checked, "declared": d.declared}


def test_the_rejected_option_headline_is_the_most_expensive_candidate_not_chosen(client: Roadmap, rec: Recommendation) -> None:
    h = next(x for x in client.headlines if x.id == "rejected_option")
    chosen = {c.package_id: c.strategy for c in client.portfolio.constrained.choices}
    costs = [o.migration_cost_jpy for pid, w in rec.work_packages.items() for o in w.options
             if o.eligible and o.strategy != chosen[pid] and o.migration_cost_jpy is not None]
    assert h.numbers["migration_cost_jpy"] == max(costs)
    assert "rejected because" in h.text


def test_the_breakeven_headline_names_the_largest_value_at_stake_within_ten_times(client: Roadmap, rec: Recommendation) -> None:
    h = next(x for x in client.headlines if x.id == "breakeven_question")
    weights = {c.package_id: c.weight for c in client.portfolio.constrained.choices}
    eligible = {}
    for pid, w in rec.work_packages.items():
        assert w.breakeven is not None
        if any(o.multiple_of_baseline and 0.1 <= o.multiple_of_baseline <= 10 for o in w.breakeven.overtaking):
            eligible[pid] = weights[pid]
    top = max(eligible, key=lambda k: (eligible[k], k))
    assert top in h.text and h.numbers["share_of_do_nothing_cost"] == round(eligible[top], 4)
    multiple = float(h.numbers["multiple_of_baseline"])
    assert float(h.numbers["breakeven_jpy_per_year"]) > 0 and 0.1 <= multiple <= 10


def test_the_breakeven_headline_degrades_gracefully_without_the_analysis(
        tight_rec: Recommendation, analysis: AnalysisResult, tight_scenario: ClientScenario, rcfg: RoadmapConfig) -> None:
    rm = make(tight_rec, analysis, tight_scenario, rcfg, "long_term_value")  # tight_rec was computed without sensitivity
    h = next(x for x in rm.headlines if x.id == "breakeven_question")
    assert "has not been computed" in h.text and h.numbers == {}


def test_the_largest_exposure_headline_follows_the_weights(ltv: Roadmap) -> None:
    h = next(x for x in ltv.headlines if x.id == "largest_exposure")
    top = max(ltv.portfolio.constrained.choices, key=lambda c: (c.weight, c.package_id))
    assert top.package_id in h.text and h.numbers["share_of_do_nothing_cost"] == round(top.weight, 4)


def test_a_binding_budget_is_mentioned_in_the_portfolio_headline(ltv: Roadmap) -> None:
    h = next(x for x in ltv.headlines if x.id == "portfolio")
    assert h.numbers["budget_downgrades"] == len(ltv.portfolio.downgrades) and "budget forced" in h.text
