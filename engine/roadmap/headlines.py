"""Estate-level headline findings: deterministic sentences built only from the numbers (no LLM).

They become the UI's executive summary and, later, the LLM's input (so the LLM only rephrases facts it is given).
Every sentence carries the numbers it states in `numbers`, so a checker can confirm each figure appears in the output.
"""

from __future__ import annotations

import math

from analyzer.schema import AnalysisResult
from engine.roadmap.schema import Economics, Headline, Item, Opportunity, PortfolioSelection
from engine.schema import Recommendation, WorkPackageReport

BREAKEVEN_MAX_MULTIPLE = 10.0  # a breakeven more than 10x the baseline is not a realistic estimation error


def money(x: float) -> str:
    return f"JPY {x / 1e6:,.1f} million" if abs(x) >= 1e6 else f"JPY {x:,.0f}"


def _mix(mix: dict[str, int]) -> str:
    parts = [f"{n} {s}" for s, n in sorted(mix.items(), key=lambda kv: (-kv[1], kv[0]))]
    return ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] if parts else "no work"


def _portfolio(sel: PortfolioSelection, finish: int | None) -> Headline:
    c = sel.constrained
    text = (f"Under the {sel.profile} priorities the recommended portfolio is {_mix(c.strategy_mix)} across {len(c.choices)} work "
            f"packages, costing {money(c.total_migration_cost_jpy)} to migrate against a budget ceiling of {money(sel.budget_ceiling_jpy)}")
    text += f"; the programme finishes in month {finish}." if finish else "; nothing needs to be scheduled."
    numbers: dict[str, float | int | str] = {"migration_cost_jpy": c.total_migration_cost_jpy, "budget_ceiling_jpy": sel.budget_ceiling_jpy,
                                             "packages": len(c.choices), "finish_month": finish or 0}
    if sel.downgrades:
        text += (f" The budget forced {len(sel.downgrades)} packages onto a cheaper option than their unconstrained best, "
                 f"saving {money(sum(d.migration_cost_saved_jpy for d in sel.downgrades))}.")
        numbers["budget_downgrades"] = len(sel.downgrades)
    return Headline(id="portfolio", kind="portfolio", text=text, numbers=numbers)


def _value(e: Economics) -> Headline:
    years = e.horizon_months // 12
    pays = (f"pays back in quarter {e.payback_quarter} (month {e.payback_quarter * 3})" if e.payback_quarter
            else f"does not pay back within the {years}-year horizon")
    direction = "ahead" if e.npv_vs_retain_jpy >= 0 else "behind"
    text = (f"Against doing nothing, the programme leaves the client {money(abs(e.npv_vs_retain_jpy))} {direction} in present-value terms "
            f"over {years} years (NPV vs retain {money(e.npv_vs_retain_jpy)}), {pays}; peak investment is {money(e.peak_investment_jpy)}")
    text += f" in quarter {e.peak_investment_quarter}." if e.peak_investment_quarter else "."
    return Headline(id="value", kind="value", text=text, numbers={
        "npv_vs_retain_jpy": e.npv_vs_retain_jpy, "payback_quarter": e.payback_quarter or 0, "peak_investment_jpy": e.peak_investment_jpy,
        "total_programme_cost_jpy": e.total_programme_cost_jpy, "horizon_years": years})


def _largest_exposure(rec: Recommendation, sel: PortfolioSelection, items: list[Item]) -> Headline:
    choice = max(sel.constrained.choices, key=lambda c: (c.weight, c.package_id))
    w = rec.work_packages[choice.package_id]
    when = next((i for i in items if i.package_id == choice.package_id), None)
    what = (f"it is scheduled as {choice.strategy} in months {when.start_month} to {when.end_month}" if when
            else "it is left as it is (retained)" if choice.strategy == "retain" else f"it is chosen as {choice.strategy}")
    text = (f"The largest value at stake is {w.name} ({choice.package_id}), {choice.weight:.0%} of the estate's five-year do-nothing cost; "
            f"in this portfolio {what}.")
    return Headline(id="largest_exposure", kind="largest_exposure", text=text, numbers={
        "share_of_do_nothing_cost": round(choice.weight, 4), "loc": w.loc, "migration_cost_jpy": choice.migration_cost_jpy})


def _rejected(rec: Recommendation, sel: PortfolioSelection) -> Headline:
    chosen = {c.package_id: c.strategy for c in sel.constrained.choices}
    downgraded = {d.package_id: d.unconstrained for d in sel.downgrades}
    best: tuple[int, str, str] | None = None
    for pid, w in sorted(rec.work_packages.items()):
        for o in w.options:
            if o.eligible and o.strategy != chosen[pid] and o.migration_cost_jpy is not None:
                key = (o.migration_cost_jpy, pid, o.strategy)
                best = key if best is None or key[0] > best[0] else best
    if best is None:
        return Headline(id="rejected_option", kind="rejected_option", text="No option was rejected: every package has a single candidate.", numbers={})
    cost, pid, strategy = best
    pkg: WorkPackageReport = rec.work_packages[pid]
    o = next(x for x in pkg.options if x.strategy == strategy)
    if not o.feasible:
        why = f"it breaks a client constraint: {o.infeasible_reasons[0]}"
    elif downgraded.get(pid) == strategy:
        why = f"it did not fit the budget ceiling of {money(sel.budget_ceiling_jpy)} once the whole portfolio is considered"
    else:
        ranking: dict[str, float] = {s.strategy: s.score for s in pkg.choices[sel.profile].ranking}
        gap = ranking[chosen[pid]] - ranking.get(strategy, 0.0)
        why = f"it scored {gap:.1f} points below the chosen {chosen[pid]} under the {sel.profile} priorities"
    tco = o.tco.tco_jpy if o.tco else 0
    retain = next(x for x in pkg.options if x.strategy == "retain").tco
    text = (f"The most expensive option considered and rejected is {strategy} for {pkg.name} ({pid}): {money(cost)} to migrate and "
            f"{money(tco)} in five-year TCO against {money(retain.tco_jpy if retain else 0)} for doing nothing; it was rejected because {why}.")
    return Headline(id="rejected_option", kind="rejected_option", text=text, numbers={
        "migration_cost_jpy": cost, "tco_jpy": tco, "retain_tco_jpy": retain.tco_jpy if retain else 0})


def _breakeven(rec: Recommendation, sel: PortfolioSelection) -> Headline:
    weights = {c.package_id: c.weight for c in sel.constrained.choices}
    if sel.profile != rec.meta.selected_profile or any(w.breakeven is None for w in rec.work_packages.values()):
        return Headline(id="breakeven_question", kind="breakeven_question", numbers={},
                        text="The breakeven analysis (how wrong the maintenance-spend estimate would have to be to change a recommendation) "
                             "has not been computed for this profile.")
    candidates: list[tuple[float, str, str, float, float]] = []
    for pid, w in rec.work_packages.items():
        b = w.breakeven
        assert b is not None
        near = [o for o in b.overtaking if o.multiple_of_baseline and 1 / BREAKEVEN_MAX_MULTIPLE <= o.multiple_of_baseline <= BREAKEVEN_MAX_MULTIPLE]
        if near:
            o = min(near, key=lambda x: abs(math.log(x.multiple_of_baseline or 1.0)))
            candidates.append((weights[pid], pid, o.strategy, o.breakeven_jpy_per_year or 0.0, b.baseline_jpy_per_year))
    if not candidates:
        return Headline(id="breakeven_question", kind="breakeven_question", numbers={},
                        text=f"No recommendation changes if any package's yearly maintenance spend is off by up to {BREAKEVEN_MAX_MULTIPLE:g} times: "
                             "the choices are not sensitive to that assumption.")
    weight, pid, strategy, be, base = max(candidates, key=lambda c: (c[0], c[1]))
    w = rec.work_packages[pid]
    text = (f"The assumption most worth validating with the client is the yearly maintenance spend of {w.name} ({pid}): the model assumes "
            f"{money(base)}, and at {money(be)} ({be / base:.1f} times) {strategy} would overtake {w.choices[sel.profile].chosen}, the best option for "
            f"this package under these priorities before any budget limit; "
            f"this package carries {weight:.0%} of the estate's five-year do-nothing cost.")
    return Headline(id="breakeven_question", kind="breakeven_question", text=text, numbers={
        "model_baseline_jpy_per_year": round(base), "breakeven_jpy_per_year": round(be), "multiple_of_baseline": round(be / base, 2),
        "share_of_do_nothing_cost": round(weight, 4)})


def _calibration(rec: Recommendation) -> Headline | None:
    k = next((x for x in rec.kpi_reconciliation if x.objective == "maintenance_cost" and x.model_baseline is not None), None)
    if k is None or k.gap_pct is None:
        return None
    flag = "; the gap exceeds the tolerance, so the client's own figure should replace the model's estimate" if k.flagged else ""
    return Headline(id="calibration", kind="calibration", numbers={
        "model_baseline_million_jpy": k.model_baseline or 0.0, "scope_adjusted_kpi_million_jpy": k.kpi_current_in_analysed_scope, "gap_pct": k.gap_pct},
        text=(f"For the analysed scope the model estimates maintenance at JPY {k.model_baseline:,.1f} million a year against a scope-adjusted client "
              f"figure of JPY {k.kpi_current_in_analysed_scope:,.1f} million ({k.gap_pct:+.0f}%){flag}."))


def _unlocks(unlocks: list[Opportunity]) -> Headline:
    done = [u for u in unlocks if u.status == "unlocked"]
    if done:
        names = "; ".join(f"{u.name} (from month {u.available_from_month})" for u in done)
        text = f"{len(done)} of {len(unlocks)} data and AI opportunities are unlocked by the modernized packages: {names}."
    else:
        text = f"None of the {len(unlocks)} data and AI opportunities is unlocked: the chosen strategies do not expose the required APIs."
    return Headline(id="unlocks", kind="unlocks", text=text, numbers={"unlocked": len(done), "opportunities": len(unlocks)})


def _broken(analysis: AnalysisResult) -> Headline:
    found = [f for f in analysis.findings if f.kind == "broken_reference"]
    if not found:
        return Headline(id="broken_references", kind="broken_references", text="No broken service or controller references were found.",
                        numbers={"count": 0})
    shown = "; ".join(f"{f.subject} ({(f.file or '').rsplit('/', 1)[-1]}:{f.line})" for f in found[:3])
    more = f", and {len(found) - 3} more" if len(found) > 3 else ""
    return Headline(id="broken_references", kind="broken_references", numbers={"count": len(found)},
                    text=f"{len(found)} service or controller definitions point at code that does not exist: {shown}{more}.")


def _dependencies(rec: Recommendation) -> Headline:
    d = rec.estate_findings
    return Headline(id="dependencies", kind="dependencies", numbers={"outdated": d.outdated, "checked": d.checked, "declared": d.declared},
                    text=f"{d.outdated} of {d.checked} checked third-party dependencies are outdated (of {d.declared} declared).")


def build_headlines(rec: Recommendation, analysis: AnalysisResult, selection: PortfolioSelection, items: list[Item],
                    economics: Economics, unlocks: list[Opportunity], finish_month: int | None) -> list[Headline]:
    out = [_portfolio(selection, finish_month), _value(economics), _largest_exposure(rec, selection, items),
           _rejected(rec, selection), _breakeven(rec, selection)]
    cal = _calibration(rec)
    if cal:
        out.append(cal)
    return out + [_unlocks(unlocks), _broken(analysis), _dependencies(rec)]
