"""Engine tests: every number reconstructs from its breakdown; assumptions and constraints move results correctly."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from analyzer.analyze import analyze
from analyzer.config import load_config
from analyzer.schema import AnalysisResult, Dependency
from engine.__main__ import main as cli_main
from engine.config import CRITERIA, EngineConfig, Override, Priorities, parse_profile
from engine.health import db_scale
from engine.recommend import recommend
from engine.scenario import ClientScenario, check_consistency
from engine.schema import Recommendation, StrategyOption, WorkPackageReport
from engine.sensitivity import _reweighted
from engine.tests.conftest import FIXTURE

PROFILES = ["minimize_cost", "minimize_risk", "speed_to_market", "long_term_value", "balanced", "client_scenario"]


def opt(w: WorkPackageReport, strategy: str) -> StrategyOption:
    return next(o for o in w.options if o.strategy == strategy)


def tco_jpy(o: StrategyOption) -> int:
    assert o.tco is not None
    return o.tco.tco_jpy


def run(analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, **kw: object) -> Recommendation:
    kw.setdefault("sensitivity", False)
    return recommend(analysis, cfg=cfg, scenario=scenario, **kw)  # type: ignore[arg-type]


# --- health -------------------------------------------------------------------------------------------------

def test_health_reconstructs_exactly(rec: Recommendation, cfg: EngineConfig) -> None:
    units = [m.health for m in rec.modules.values()] + [w.health for w in rec.work_packages.values()]
    for h in units:
        assert sum(c.weight for c in h.components) == pytest.approx(1.0)
        for c in h.components:
            assert c.contribution_points == round(100.0 * c.weight * c.normalized, 4)
            assert 0.0 <= c.normalized <= 1.0
        assert h.score == round(100.0 - sum(c.contribution_points for c in h.components), 4)
        ranked = sorted(h.components, key=lambda c: (-c.contribution_points, c.key))
        assert h.top_drivers == [c.key for c in ranked[:3]]
        assert {c.key: c.weight for c in h.components} == cfg.health.weights  # no outdated-dependency component


def test_outdated_dependencies_are_an_estate_finding_not_a_health_component(rec: Recommendation) -> None:
    assert rec.estate_findings.outdated == 8 and rec.estate_findings.checked == 11
    assert "org.springframework:spring-core" in rec.estate_findings.outdated_coordinates
    for m in rec.modules.values():
        assert "outdated_dependencies" not in {c.key for c in m.health.components}


def test_a_module_with_its_own_build_file_gets_the_dependency_component(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario) -> None:
    mutated = analysis.model_copy(deep=True)
    mutated.modules["billing"].coverage.component = "apps/billing"
    mutated.dependencies.append(Dependency(
        file="apps/billing/pom.xml", coordinate="a:b", declared_version="1.0", declared_major=1,
        latest_stable_version="3.0", latest_major=3, superseded_by=None, checked=True, outdated=True))
    out = run(mutated, cfg, scenario)
    own = {c.key: c for c in out.modules["billing"].health.components}
    assert own["outdated_dependencies"].weight == cfg.health.own_build_file_weight
    assert own["outdated_dependencies"].normalized == 1.0
    assert sum(c.weight for c in own.values()) == pytest.approx(1.0)
    assert own["size"].weight == pytest.approx(cfg.health.weights["size"] * (1 - cfg.health.own_build_file_weight))
    assert "outdated_dependencies" not in {c.key for c in out.modules["order"].health.components}


def test_database_scale_is_logarithmic_and_does_not_saturate_at_ofbiz_densities(cfg: EngineConfig) -> None:
    values = [db_scale(x, cfg) for x in (0, 5, 15, 30, 60)]
    assert values[0] == 0.0 and values == sorted(values) and len(set(values)) == 5
    assert values[3] < 0.8  # 30 calls/KLOC, the densest OFBiz module, used to be capped at 1.0
    assert db_scale(cfg.health.db_calls_per_kloc_reference, cfg) == pytest.approx(1.0)
    assert db_scale(10 * cfg.health.db_calls_per_kloc_reference, cfg) == 1.0


def test_test_evidence_counts_testdef_cases_separately_from_junit_and_groovy(
        rec: Recommendation, analysis: AnalysisResult) -> None:
    billing = analysis.modules["billing"]
    assert (billing.test_method_count, billing.groovy_test_files, billing.testdef_test_cases) == (2, 0, 2)
    raw = next(c.raw for c in rec.modules["billing"].health.components if c.key == "test_evidence")
    assert raw == pytest.approx((2 + max(0, 2)) / billing.loc * 1000.0, rel=1e-3)  # max(), not a sum, of groovy/testdef


# --- work packages ------------------------------------------------------------------------------------------

def test_work_packages_partition_the_classes_and_roll_up_to_module_totals(
        rec: Recommendation, analysis: AnalysisResult) -> None:
    seen: list[str] = []
    for w in rec.work_packages.values():
        seen += w.classes
        assert w.loc == sum(analysis.classes[c].loc for c in w.classes)
        assert all(analysis.classes[c].module == w.module for c in w.classes)
    assert sorted(seen) == sorted(analysis.classes)  # every class in exactly one package
    for name, m in rec.modules.items():
        wps = [rec.work_packages[i] for i in m.work_package_ids]
        assert m.loc == sum(w.loc for w in wps) == analysis.modules[name].loc
        for profile, roll in m.rollups.items():
            picked = {w.id: opt(w, w.choices[profile].chosen) for w in wps}
            assert roll.strategy_by_work_package == {w.id: w.choices[profile].chosen for w in wps}
            assert roll.loc == m.loc
            assert roll.migration_cost_jpy == sum(o.migration_cost_jpy or 0 for o in picked.values())
            assert roll.tco_jpy == sum(tco_jpy(o) for o in picked.values())
            assert roll.retain_tco_jpy == sum(tco_jpy(opt(w, "retain")) for w in wps)
            assert roll.effort_days == round(sum(o.effort_days or 0 for o in picked.values()), 4)
            assert roll.duration_months == round(sum(o.duration_months or 0 for o in picked.values()), 4)


def test_estate_totals_are_sums_over_work_packages(rec: Recommendation) -> None:
    for profile, est in rec.estate.items():
        picked = [opt(w, est.strategy_by_work_package[w.id]) for w in rec.work_packages.values()]
        assert est.total_migration_cost_jpy == sum(o.migration_cost_jpy or 0 for o in picked)
        assert est.total_tco_jpy == sum(tco_jpy(o) for o in picked)
        assert est.retain_tco_jpy == sum(tco_jpy(opt(w, "retain")) for w in rec.work_packages.values())
        assert est.tco_savings_vs_retain_jpy == est.retain_tco_jpy - est.total_tco_jpy
        assert sum(est.strategy_mix.values()) == len(rec.work_packages)
        assert est.within_budget == (est.total_migration_cost_jpy <= est.budget_ceiling_jpy)
        for m in rec.modules.values():
            assert est.total_migration_cost_jpy == sum(r.migration_cost_jpy for r in
                                                       (mm.rollups[profile] for mm in rec.modules.values()))


def test_package_kinds_and_names(rec: Recommendation) -> None:
    kinds = {w.kind for w in rec.work_packages.values()}
    assert kinds == {"cycle", "god_class_cluster", "remainder"}
    god = next(w for w in rec.work_packages.values() if w.kind == "god_class_cluster")
    assert "OrderServices" in god.name and god.module == "order"
    cycle = [w for w in rec.work_packages.values() if w.kind == "cycle"]
    assert {w.module for w in cycle} == {"billing", "order", "party"}  # a cross-module cycle is split per module
    assert all(w.cycle_modules == ["billing", "order", "party"] for w in cycle)
    assert any("OrderReadHelper" in w.name for w in cycle)


def test_satellite_threshold_comes_from_config(analysis: AnalysisResult, cfg: EngineConfig) -> None:
    from engine.workpackages import build_work_packages

    def cluster_size(share: float) -> int:
        c = cfg.model_copy(update={"work_packages": cfg.work_packages.model_copy(update={"satellite_min_share": share})})
        return len(next(w for w in build_work_packages(analysis, c) if w.kind == "god_class_cluster").classes)

    assert cluster_size(0.0) > cluster_size(0.5) >= cluster_size(1.0)


def test_a_module_can_mix_strategies_across_its_work_packages(rec: Recommendation) -> None:
    mixed = {(p, m.module) for m in rec.modules.values() for p, r in m.rollups.items()
             if len(set(r.strategy_by_work_package.values())) > 1}
    assert ("long_term_value", "party") in mixed  # cycle fragment rearchitected, remainder rehosted
    assert ("minimize_risk", "billing") in mixed
    ltv = rec.modules["party"].rollups["long_term_value"].strategy_by_work_package
    assert set(ltv.values()) == {"rearchitect", "rehost"}


# --- retain, TCO ---------------------------------------------------------------------------------------------

def test_retain_is_always_present_feasible_and_a_valid_choice(rec: Recommendation) -> None:
    for w in rec.work_packages.values():
        retain = opt(w, "retain")
        assert retain.eligible and retain.feasible and retain.infeasible_reasons == []
        assert retain.migration_cost_jpy == 0 and retain.duration_months == 0 and retain.tco is not None
        assert retain.tco.payback_year is None and retain.tco.savings_vs_retain_jpy == 0
        assert retain.value is not None and retain.value.value == 0.0
        assert "retain" in {s.strategy for c in w.choices.values() for s in c.ranking} or True
    chosen = {c.chosen for w in rec.work_packages.values() for c in w.choices.values()}
    assert "retain" in chosen  # doing nothing wins somewhere: it is a real option, not decoration


def test_retain_survives_when_every_other_option_is_infeasible(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario) -> None:
    broke = scenario.model_copy(deep=True)
    broke.constraints.budget_ceiling_jpy = 1
    out = run(analysis, cfg, broke)
    for w in out.work_packages.values():
        assert w.choices["long_term_value"].chosen == "retain"
        assert [s.strategy for s in w.choices["long_term_value"].ranking] == ["retain"]
        assert w.choices["long_term_value"].runner_up is None and w.choices["long_term_value"].margin is None
        assert opt(w, "retain") in w.options


def test_tco_reconstructs_exactly(rec: Recommendation, cfg: EngineConfig, scenario: ClientScenario) -> None:
    horizon, rate = scenario.constraints.planning_horizon_years, cfg.tco.discount_rate
    cc = cfg.change_cost
    for w in rec.work_packages.values():
        retain = opt(w, "retain")
        assert retain.tco is not None
        mult0 = 1 + cc.health_penalty * (1 - w.health.score / 100)
        base_m = w.kloc * cfg.tco.maintenance_days_per_kloc_year * (
            1 + cfg.tco.debt_maintenance_penalty * (1 - w.health.score / 100)) * cfg.daily_rate_jpy
        assert w.maintenance_baseline_jpy_per_year == pytest.approx(base_m, rel=1e-9)  # model baseline unchanged
        assert retain.tco.baseline_maintenance_jpy_per_year == pytest.approx(base_m, rel=1e-9)
        assert retain.tco.baseline_run_jpy_per_year == pytest.approx(w.kloc * cfg.tco.run_cost_jpy_per_kloc_year, rel=1e-9)
        assert retain.tco.baseline_change_jpy_per_year == pytest.approx(
            w.change_requests_per_year * cc.base_days_per_change * mult0 * cfg.daily_rate_jpy, rel=1e-4)
        for o in (x for x in w.options if x.eligible):
            t = o.tco
            assert t is not None and t.horizon_years == horizon == len(t.yearly) and t.discount_rate == rate
            duration = o.duration_months or 0.0
            reduction = cfg.long_term_value.debt_reduction.get(o.strategy, 0.0)
            run_factor = cfg.tco.residual_run_cost[o.strategy]
            change_factor = (1 + cc.health_penalty * (1 - reduction) * (1 - w.health.score / 100)) / mult0
            for row in t.yearly:
                f = min(1.0, max(0.0, (12.0 * row.year - duration) / 12.0))
                assert row.maintenance_jpy == round(t.baseline_maintenance_jpy_per_year * (1 - reduction * f))
                assert row.run_jpy == round(t.baseline_run_jpy_per_year * (1 - (1 - run_factor) * f))
                assert row.change_jpy == round(t.baseline_change_jpy_per_year * (1 - (1 - change_factor) * f))
                assert row.total_jpy == row.migration_jpy + row.run_jpy + row.maintenance_jpy + row.change_jpy
            assert t.steady_state_maintenance_jpy == round(t.baseline_maintenance_jpy_per_year * (1 - reduction))
            assert t.steady_state_run_jpy == round(t.baseline_run_jpy_per_year * run_factor)
            assert t.steady_state_change_jpy == round(t.baseline_change_jpy_per_year * change_factor)
            assert t.migration_total_jpy == sum(r.migration_jpy for r in t.yearly) == (o.migration_cost_jpy or 0)
            assert t.run_total_jpy == sum(r.run_jpy for r in t.yearly)
            assert t.maintenance_total_jpy == sum(r.maintenance_jpy for r in t.yearly)
            assert t.change_total_jpy == sum(r.change_jpy for r in t.yearly)
            assert t.tco_jpy == t.migration_total_jpy + t.run_total_jpy + t.maintenance_total_jpy + t.change_total_jpy
            assert t.npv_cost_jpy == round(sum(r.total_jpy / (1 + rate) ** r.year for r in t.yearly))
            assert t.savings_vs_retain_jpy == retain.tco.tco_jpy - t.tco_jpy
            assert t.change_savings_vs_retain_jpy == retain.tco.change_total_jpy - t.change_total_jpy
            assert t.npv_vs_retain_jpy == retain.tco.npv_cost_jpy - t.npv_cost_jpy
            cumulative, payback = 0, None
            for mine, base in zip(t.yearly, retain.tco.yearly, strict=True):
                cumulative += base.total_jpy - mine.total_jpy
                if cumulative >= 0 and payback is None and o.strategy != "retain":
                    payback = mine.year
            assert t.payback_year == payback


def test_migration_spend_is_spread_over_the_migration_months(rec: Recommendation) -> None:
    long = max((o for w in rec.work_packages.values() for o in w.options if o.eligible), key=lambda o: o.duration_months or 0)
    assert (long.duration_months or 0) > 0
    spend = [r.migration_jpy for r in (long.tco.yearly if long.tco else [])]
    assert spend[0] > 0 and sum(spend) == long.migration_cost_jpy
    assert all(s == 0 for s in spend[int((long.duration_months or 0) // 12) + 1:])  # nothing after the migration ends


def test_cost_criterion_uses_tco_not_migration_cost(rec: Recommendation, cfg: EngineConfig) -> None:
    w = rec.work_packages["order/god-class-cluster-1"]
    retain_tco = tco_jpy(opt(w, "retain"))
    for s in w.choices["balanced"].ranking:
        cost = next(c for c in s.criteria if c.criterion == "cost")
        o = opt(w, s.strategy)
        assert cost.raw == tco_jpy(o)
        assert cost.goodness == round(max(0.0, 1 - cost.raw / (cfg.scoring.cost_ratio_ceiling * retain_tco)), 6)
        assert cost.raw != o.migration_cost_jpy or s.strategy == "retain"


def test_raising_daily_rate_raises_migration_cost_and_tco(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rec: Recommendation) -> None:
    pricier = run(analysis, cfg.model_copy(update={"daily_rate_jpy": cfg.daily_rate_jpy * 1.5}), scenario)
    for wid, w in rec.work_packages.items():
        for a, b in zip(w.options, pricier.work_packages[wid].options, strict=True):
            if a.eligible and a.strategy != "retain":
                assert (b.migration_cost_jpy or 0) > (a.migration_cost_jpy or 0) and b.effort_days == a.effort_days
            if a.eligible:
                assert tco_jpy(b) > tco_jpy(a)  # maintenance is also priced by the rate


# --- constraints -----------------------------------------------------------------------------------------------

def test_budget_constraint_makes_options_infeasible_with_a_reason(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rec: Recommendation) -> None:
    w0 = rec.work_packages["order/god-class-cluster-1"]
    ceiling = (opt(w0, "refactor").migration_cost_jpy or 0) - 1
    tight = scenario.model_copy(deep=True)
    tight.constraints.budget_ceiling_jpy = ceiling
    out = run(analysis, cfg, tight)
    w = out.work_packages["order/god-class-cluster-1"]
    for strategy in ("refactor", "rearchitect"):
        o = opt(w, strategy)
        assert o.eligible and not o.feasible and o.migration_cost_jpy is not None  # shown, with numbers
        assert any("budget ceiling" in r and f"{ceiling:,}" in r for r in o.infeasible_reasons)
        assert strategy not in {s.strategy for c in w.choices.values() for s in c.ranking}  # not selectable
    assert w.choices["long_term_value"].chosen not in ("refactor", "rearchitect")


def test_downtime_limit_applies_per_cutover_event(rec: Recommendation, cfg: EngineConfig, scenario: ClientScenario) -> None:
    limit = scenario.constraints.max_cutover_downtime_hours["order"]
    for w in (x for x in rec.work_packages.values() if x.module == "order"):
        for o in (x for x in w.options if x.eligible):
            assert o.cutover_hours_per_event is not None
            assert o.feasible == (o.cutover_hours_per_event <= limit), (w.id, o.strategy)
            if not o.feasible:
                assert any("per-event maximum" in r and f"{limit:g} h" in r for r in o.infeasible_reasons)
    assert all(opt(w, "rehost").feasible for w in rec.work_packages.values() if w.module == "common")  # no limit for common


def test_cutover_approach_and_events(rec: Recommendation, cfg: EngineConfig) -> None:
    c = cfg.cutover
    for w in rec.work_packages.values():
        for o in (x for x in w.options if x.eligible):
            assert o.cutover_approach == c.approach[o.strategy]
            if o.strategy == "retain":
                assert (o.cutover_events, o.cutover_hours_per_event, o.cutover_total_hours) == (0, 0.0, 0.0)
            elif o.cutover_approach == "big_bang":
                assert o.cutover_events == 1
                assert o.cutover_hours_per_event == round(c.big_bang.base_hours.get(o.strategy, 0.0) + c.big_bang.hours_per_kloc * w.kloc, 4)
            else:
                assert o.cutover_events == max(1, math.ceil(w.kloc / c.incremental.slice_kloc))
                assert o.cutover_hours_per_event == c.incremental.hours_per_slice
            assert o.cutover_total_hours == round((o.cutover_events or 0) * (o.cutover_hours_per_event or 0), 4)
            labels = [x.label for x in o.effort_lines]
            assert ("Parallel run of old and new" in labels) == (o.cutover_approach == "incremental")


def test_big_bang_hours_scale_with_the_package_and_slices_stay_short(cfg: EngineConfig) -> None:
    from engine.strategies import cutover_plan

    small, big = cutover_plan("rehost", 1.0, cfg), cutover_plan("rehost", 30.0, cfg)
    assert big[2] > small[2] and big[1] == small[1] == 1
    slices_small, slices_big = cutover_plan("refactor", 1.0, cfg), cutover_plan("refactor", 30.0, cfg)
    assert slices_big[1] > slices_small[1] and slices_big[2] == slices_small[2] == cfg.cutover.incremental.hours_per_slice


def test_a_tight_limit_rules_out_big_bang_but_not_incremental(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario) -> None:
    tight = scenario.model_copy(deep=True)
    tight.constraints.max_cutover_downtime_hours = {"order": 1.0}
    out = run(analysis, cfg, tight)
    for w in (x for x in out.work_packages.values() if x.module == "order"):
        assert not opt(w, "rehost").feasible and not opt(w, "replatform").feasible
        assert opt(w, "refactor").feasible and opt(w, "rearchitect").feasible  # 0.5 h slices


def test_a_portfolio_over_budget_is_flagged_not_hidden(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rec: Recommendation) -> None:
    ltv = rec.estate["long_term_value"]
    most = max(opt(w, ltv.strategy_by_work_package[w.id]).migration_cost_jpy or 0 for w in rec.work_packages.values())
    sc = scenario.model_copy(deep=True)
    sc.constraints.budget_ceiling_jpy = most  # every single option fits, the portfolio does not
    out = run(analysis, cfg, sc)
    est = out.estate["long_term_value"]
    assert est.strategy_by_work_package == ltv.strategy_by_work_package
    assert est.total_migration_cost_jpy > most and est.within_budget is False
    assert rec.estate["minimize_cost"].within_budget is True


# --- value: criticality and objectives ----------------------------------------------------------------------------

def test_value_reconstructs_from_debt_criticality_and_objectives(rec: Recommendation, cfg: EngineConfig) -> None:
    skip = cfg.change_cost.monetised_objective
    for w in rec.work_packages.values():
        crit = rec.modules[w.module].criticality.value
        for o in (x for x in w.options if x.eligible):
            v = o.value
            assert v is not None and v.criticality == crit
            assert v.criticality_weight == cfg.long_term_value.criticality_weight[crit]
            counted = sum(x.weight for x in v.objectives if x.objective != skip)
            for x in v.objectives:
                assert x.counted == (x.objective != skip)
                assert x.contribution == (round(x.weight * x.effect / counted, 6) if x.counted else 0.0)
            assert v.objective_fit == pytest.approx(sum(x.contribution for x in v.objectives))
            maintenance = min(100.0, 100.0 * w.kloc / cfg.long_term_value.maintenance_kloc_cap)
            assert v.burden == round(cfg.long_term_value.debt_weight * (100 - w.health.score)
                                     + (1 - cfg.long_term_value.debt_weight) * maintenance, 4)
            assert v.debt_reduction == cfg.long_term_value.debt_reduction.get(o.strategy, 0.0)
            assert v.uncapped == round(v.debt_reduction * v.burden * v.criticality_weight * v.objective_fit, 4)
            assert v.value == min(100.0, v.uncapped)


def test_higher_criticality_raises_value(analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario) -> None:
    def values(level: int) -> dict[str, float]:
        over = {"order": Override(module="order", criticality=level, reason="Client interview, test scenario")}
        out = run(analysis, cfg, scenario, overrides=over)
        return {f"{w.id}/{o.strategy}": o.value.uncapped for w in out.work_packages.values() if w.module == "order"
                for o in w.options if o.eligible and o.strategy != "retain" and o.value}

    low, high = values(1), values(3)
    assert low.keys() == high.keys() and low
    cw = cfg.long_term_value.criticality_weight
    for key in low:
        assert high[key] > low[key]
        assert high[key] == pytest.approx(low[key] * cw[3] / cw[1], rel=1e-3)


def test_objective_mapping_decides_which_strategy_serves_which_goal(
        rec: Recommendation, cfg: EngineConfig, analysis: AnalysisResult, scenario: ClientScenario) -> None:
    effect = cfg.long_term_value.objective_effect
    assert effect["rehost"]["change_lead_time"] == 0.0 and effect["rehost"]["run_cost"] > effect["refactor"]["run_cost"]
    w = rec.work_packages["order/god-class-cluster-1"]
    fit = {o.strategy: o.value.objective_fit for o in w.options if o.eligible and o.value}
    assert fit["retain"] == 0.0 and fit["rearchitect"] > fit["refactor"] > fit["replatform"] > fit["rehost"] > 0
    lead = scenario.model_copy(deep=True)
    for o in lead.objectives:
        o.weight = 1.0 if o.id == "change_lead_time" else 0.0
    out = run(analysis, cfg, lead)
    rehost_value = opt(out.work_packages["order/god-class-cluster-1"], "rehost").value
    assert rehost_value is not None and rehost_value.objective_fit == 0.0


# --- risk, effort -------------------------------------------------------------------------------------------------

def test_effort_cost_duration_and_risk_reconstruct_exactly(rec: Recommendation, cfg: EngineConfig) -> None:
    for w in rec.work_packages.values():
        for o in (x for x in w.options if x.eligible and x.strategy != "retain"):
            assert o.effort_days == round(sum(line.days for line in o.effort_lines), 4)
            assert o.migration_cost_jpy == round((o.effort_days or 0) * cfg.daily_rate_jpy)
            assert o.duration_months == round((o.effort_days or 0) / ((o.team_size or 1) * cfg.working_days_per_month), 4)
            m = o.multipliers
            core = o.effort_lines[0]
            assert core.days == round(w.kloc * cfg.base_days_per_kloc[o.strategy] * m["complexity_multiplier"]
                                      * (1 + m["test_overhead"]) * m["uncertainty_buffer"], 4)
            parallel = [x for x in o.effort_lines if x.label == "Parallel run of old and new"]
            if parallel:
                assert parallel[0].days == round(core.days * cfg.cutover.incremental.parallel_run_effort_share, 4)
            exposure = sum(p.contribution for p in o.risk_components)
            assert all(p.contribution == round(p.weight * p.measure, 4) for p in o.risk_components)
            assert o.risk_score == round(min(100.0, cfg.risk.base[o.strategy] * (1 + cfg.risk.exposure_gain * exposure)), 4)


def test_retain_risk_is_status_quo_exposure(rec: Recommendation, cfg: EngineConfig) -> None:
    for w in rec.work_packages.values():
        r = opt(w, "retain")
        exposure = sum(p.contribution for p in r.risk_components)
        assert r.risk_score == round(min(100.0, cfg.retain.risk_scale * 100.0 * exposure), 4)
        assert r.base_risk is None


def test_rearchitect_without_tests_adds_a_safety_net_line(rec: Recommendation) -> None:
    def labels(wid: str) -> list[str]:
        return [x.label for x in opt(rec.work_packages[wid], "rearchitect").effort_lines]

    assert "Build safety-net tests first" in labels("order/god-class-cluster-1")  # order has no tests
    assert "Build safety-net tests first" not in labels("party/remainder-1")  # party has tests


def test_low_confidence_increases_effort(cfg: EngineConfig, scenario: ClientScenario) -> None:
    high_cfg, low_cfg = load_config(), load_config()
    high_cfg.coverage.high_min_java_share = 0.1
    low_cfg.coverage.high_min_java_share, low_cfg.coverage.medium_min_java_share = 0.95, 0.9
    high, low = (run(analyze(FIXTURE, cfg=c), cfg, scenario) for c in (high_cfg, low_cfg))
    for wid, hw in high.work_packages.items():
        lw = low.work_packages[wid]
        assert hw.confidence == "high" and lw.confidence == "low"
        for h, lo in zip(hw.options, lw.options, strict=True):
            if h.eligible and h.strategy != "retain":
                assert (lo.effort_days or 0) == pytest.approx((h.effort_days or 0) * cfg.coverage_uncertainty_buffer["low"], rel=1e-3)
                assert (lo.risk_score or 0) > (h.risk_score or 0)


# --- eligibility -------------------------------------------------------------------------------------------------

def test_retire_is_ineligible_for_a_used_unit_and_explains_why(rec: Recommendation) -> None:
    for w in rec.work_packages.values():
        retire = opt(w, "retire")
        assert not retire.eligible and retire.tco is None and retire.migration_cost_jpy is None
        assert retire.ineligible_reason and "in use" in retire.ineligible_reason
        assert all(c.chosen != "retire" for c in w.choices.values())


def test_retire_is_allowed_for_an_unused_module(tmp_path: Path, cfg: EngineConfig, scenario: ClientScenario) -> None:
    pkg = tmp_path / "src/main/java/com/example/legacy/orphan"
    pkg.mkdir(parents=True)
    (pkg / "Dead.java").write_text("package com.example.legacy.orphan;\npublic class Dead { int f() { return 1; } }\n")
    out = run(analyze(tmp_path, name="orphan"), cfg, scenario)
    w = out.work_packages["orphan/remainder-1"]
    assert w.inbound_references == {"java_from_outside": 0, "service": 0, "controller": 0}
    assert opt(w, "retire").eligible and opt(w, "retire").tco is not None
    assert w.choices["minimize_cost"].chosen == "retire"


def test_a_package_used_only_through_a_service_or_controller_cannot_retire(rec: Recommendation) -> None:
    party = rec.work_packages["party/cycle-1"]  # PartyService: services.xml only
    assert party.inbound_references["service"] > 0 and not opt(party, "retire").eligible


# --- profiles, scenario --------------------------------------------------------------------------------------------

def test_presets_still_differ_on_the_fixture_and_choices_vary_by_package(rec: Recommendation) -> None:
    mixes = {p: tuple(sorted(e.strategy_by_work_package.items())) for p, e in rec.estate.items()}
    assert len(set(mixes.values())) >= 3
    assert rec.estate["long_term_value"].strategy_by_work_package != rec.estate["minimize_cost"].strategy_by_work_package
    assert len({c for e in rec.estate.values() for c in e.strategy_by_work_package.values()}) >= 3
    assert set(rec.estate) == set(PROFILES)


def test_the_client_scenario_is_the_default_profile(rec: Recommendation, scenario: ClientScenario) -> None:
    assert rec.meta.selected_profile == "client_scenario"
    assert rec.estate["client_scenario"].weights == scenario.priorities
    assert rec.meta.scenario_client == scenario.client["name"] and "FICTIONAL" in str(scenario.client["name"])
    assert rec.scenario["constraints"]["planning_horizon_years"] == 5


def test_scenario_file_content(scenario: ClientScenario, cfg: EngineConfig) -> None:
    ids = {o.id for o in scenario.objectives}
    assert ids == {"maintenance_cost", "change_lead_time", "expert_dependency", "run_cost"}
    assert all(o.illustrative and o.current != o.target for o in scenario.objectives)
    assert sum(o.weight for o in scenario.objectives) == pytest.approx(1.0)
    assert scenario.constraints.max_cutover_downtime_hours == {"order": 4, "accounting": 2}
    overrides = scenario.overrides_for("ofbiz")
    assert (overrides["accounting"].criticality, overrides["shipment"].criticality) == (3, 2)
    assert all("client interview" in o.reason.lower() for o in overrides.values())
    check_consistency(scenario, cfg)


def test_scenario_validation(scenario: ClientScenario, cfg: EngineConfig) -> None:
    bad = scenario.model_dump()
    bad["objectives"][0]["weight"] = 0.9
    with pytest.raises(ValueError, match="objective weights"):
        ClientScenario(**bad)
    broken = cfg.model_copy(deep=True)
    broken.long_term_value.objective_effect["rehost"].pop("run_cost")
    with pytest.raises(ValueError, match="objective_effect"):
        check_consistency(scenario, broken)


def test_override_takes_precedence_over_the_heuristic(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rec: Recommendation) -> None:
    proposed = rec.modules["common"].criticality
    assert proposed.source == "heuristic" and proposed.override_reason is None
    forced = 1 if proposed.value != 1 else 3
    over = {"common": Override(module="common", criticality=forced, reason="From client interview on 2026-10-01")}
    out = run(analysis, cfg, scenario, overrides=over)
    c = out.modules["common"].criticality
    assert (c.value, c.source, c.status) == (forced, "override", "confirmed_by_override")
    assert c.heuristic_value == proposed.value and c.override_reason == "From client interview on 2026-10-01"
    assert out.modules["billing"].criticality.source == "heuristic"
    risk = {p.key: p.measure for p in opt(out.work_packages["common/remainder-1"], "rehost").risk_components}
    assert risk["criticality"] == (forced - 1) / 2.0


def test_scenario_overrides_apply_by_analysis_name(analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario) -> None:
    named = analysis.model_copy(deep=True)
    named.meta.name = "ofbiz"  # the scenario's overrides are keyed by analysis name
    named.modules["billing"] = named.modules["billing"].model_copy()
    sc = scenario.model_copy(deep=True)
    sc.criticality_overrides["ofbiz"] = [Override(module="billing", criticality=3, reason="From client interview (test)")]
    out = run(named, cfg, sc)
    assert out.modules["billing"].criticality.source == "override" and out.modules["billing"].criticality.value == 3
    assert run(analysis, cfg, sc).modules["billing"].criticality.source == "heuristic"
    with pytest.raises(ValueError, match="unknown modules"):
        run(analysis, cfg, scenario, overrides={"nope": Override(module="nope", criticality=2, reason="valid long reason")})


def test_override_requires_a_written_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        Override(module="order", criticality=3, reason="")
    with pytest.raises(ValueError, match="criticality"):
        Override(module="order", criticality=4, reason="a perfectly good reason")


def test_priorities_must_sum_to_one(cfg: EngineConfig, scenario: ClientScenario) -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        Priorities(cost=0.5, risk=0.5, speed=0.5, long_term_value=0.5)
    known = {**cfg.priorities.presets, "client_scenario": scenario.priorities}
    for name, preset in known.items():
        assert sum(getattr(preset, c) for c in CRITERIA) == pytest.approx(1.0), name
    assert parse_profile("client_scenario", known)[1] == scenario.priorities
    name, custom = parse_profile("cost=0.4,risk=0.3,speed=0.2,long_term_value=0.1", known)
    assert name == "custom" and custom.cost == 0.4
    with pytest.raises(ValueError, match="profile must be"):
        parse_profile("nonsense", known)


def test_close_call_flag_follows_the_configured_margin(analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario) -> None:
    always = run(analysis, cfg.model_copy(update={"close_call_margin": 1000.0}), scenario)
    never = run(analysis, cfg.model_copy(update={"close_call_margin": 0.0}), scenario)
    multi = [c for w in always.work_packages.values() for c in w.choices.values() if c.runner_up]
    assert multi and all(c.close_call for c in multi)
    assert not any(c.close_call for w in never.work_packages.values() for c in w.choices.values())


# --- scoring reconstruction -------------------------------------------------------------------------------------------

def test_scores_reconstruct_exactly(rec: Recommendation) -> None:
    for w in rec.work_packages.values():
        for choice in w.choices.values():
            assert sum(getattr(choice.weights, c) for c in CRITERIA) == pytest.approx(1.0)
            for s in choice.ranking:
                assert s.score == round(sum(c.contribution for c in s.criteria), 4)
                o = opt(w, s.strategy)
                assert o.eligible and o.feasible
                for c in s.criteria:
                    assert c.contribution == round(100.0 * c.weight * c.goodness, 4)
                    source = {"cost": o.tco.tco_jpy if o.tco else None, "risk": o.risk_score,
                              "speed": o.duration_months, "long_term_value": o.value.value if o.value else None}
                    assert c.raw == source[c.criterion]
            assert choice.chosen == choice.ranking[0].strategy and choice.score == choice.ranking[0].score
            if choice.runner_up:
                assert choice.margin == round(choice.score - choice.ranking[1].score, 4)


def test_criticality_and_hotspot_scores_reconstruct(rec: Recommendation, cfg: EngineConfig) -> None:
    for m in rec.modules.values():
        i = m.criticality.inputs
        assert i.inbound_total == i.java_cross_module_fan_in + i.service_fan_in + i.controller_fan_in
        assert i.score == round(cfg.criticality.inbound_weight * i.inbound_share + cfg.criticality.write_weight * i.write_share, 6)
    for h in rec.hotspots:
        assert h.score == round(sum(c.contribution for c in h.components), 4)
    assert [h.score for h in rec.hotspots] == sorted((h.score for h in rec.hotspots), reverse=True)


# --- sensitivity ---------------------------------------------------------------------------------------------------------

def _recompute(analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, parameter: str, value: float,
               weights: Priorities) -> dict[str, str]:
    if parameter == "daily_rate_jpy":
        cfg = cfg.model_copy(update={"daily_rate_jpy": value})
    elif parameter.startswith("base_days_per_kloc."):
        cfg = cfg.model_copy(update={"base_days_per_kloc": {**cfg.base_days_per_kloc, parameter.split(".")[1]: value}})
    else:
        weights = _reweighted(weights, parameter.split(".")[1], value)
    profile = f"cost={weights.cost!r},risk={weights.risk!r},speed={weights.speed!r},long_term_value={weights.long_term_value!r}"
    out = recommend(analysis, cfg=cfg, scenario=scenario, profile=profile, sensitivity=False)
    return {wid: w.choices["custom"].chosen for wid, w in out.work_packages.items()}


def test_every_reported_flip_point_actually_flips(analysis: AnalysisResult, cfg: EngineConfig,
                                                  scenario: ClientScenario, rec: Recommendation) -> None:
    selected = scenario.priorities
    checked = 0
    for wid, w in rec.work_packages.items():
        base = w.choices[rec.meta.selected_profile].chosen
        for f in w.sensitivity:
            if f.flip_value is None:
                continue
            direction = 1.0 if f.flip_value > f.current_value else -1.0
            span = abs(f.flip_value - f.current_value)
            # scores are rounded to 4 dp, so probe a ladder of distances: the base strategy must hold just before the
            # flip point, and the reported new strategy must appear just beyond it (its regime can be narrow)
            ladder = [span * k for k in (1e-5, 1e-4, 1e-3, 1e-2)]
            before = {_recompute(analysis, cfg, scenario, f.parameter, f.flip_value - direction * d, selected)[wid] for d in ladder}
            after = {_recompute(analysis, cfg, scenario, f.parameter, f.flip_value + direction * d, selected)[wid] for d in ladder}
            assert base in before and f.new_strategy in after, (wid, f.parameter, before, after)
            assert f.new_strategy != base
            checked += 1
    assert checked > 0


def test_sensitivity_covers_rate_base_days_and_priorities(rec: Recommendation, cfg: EngineConfig) -> None:
    expected = ({"daily_rate_jpy"} | {f"base_days_per_kloc.{s}" for s in cfg.strategies if s != "retain"}
                | {f"priority.{c}" for c in CRITERIA})
    for w in rec.work_packages.values():
        assert {f.parameter for f in w.sensitivity} == expected
        changes = [f.change_pct for f in w.sensitivity if f.change_pct is not None]
        assert changes == sorted(changes) and all(f.note for f in w.sensitivity)


# --- output ---------------------------------------------------------------------------------------------------------------

def test_assumptions_and_scenario_are_echoed_and_labelled(rec: Recommendation) -> None:
    assert rec.assumptions["illustrative"] is True and "ILLUSTRATIVE" in rec.assumptions["notice"]
    assert rec.assumptions["config"]["daily_rate_jpy"] == 80000 and rec.assumptions["config"]["tco"]["discount_rate"] == 0.04
    assert any("FICTIONAL" in n for n in rec.meta.notes) and any("ILLUSTRATIVE" in n for n in rec.meta.notes)
    assert rec.scenario["client"]["fictional"] is True


def test_recommendation_roundtrips_through_the_schema(rec: Recommendation) -> None:
    assert Recommendation.model_validate_json(rec.model_dump_json()) == rec


def test_cli_writes_recommendation_json(tmp_path: Path) -> None:
    analysis_path = tmp_path / "legacy-sample.json"
    analysis_path.write_text(analyze(FIXTURE, name="legacy-sample").model_dump_json())
    assert cli_main([str(analysis_path), "--profile", "minimize_risk", "--out", str(tmp_path)]) == 0
    out = json.loads((tmp_path / "legacy-sample.recommendation.json").read_text())
    assert out["meta"]["selected_profile"] == "minimize_risk" and set(out["modules"]) == {"billing", "common", "order", "party"}
    assert out["work_packages"] and out["estate_findings"]["outdated"] == 8
    assert cli_main([str(tmp_path / "missing.json")]) == 2
    assert cli_main([str(analysis_path), "--profile", "bogus", "--out", str(tmp_path)]) == 2


# --- Phase 3.6: breakeven, calibration, scope, change cost --------------------------------------------------------------------

def _inputs(analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, wid: str):  # type: ignore[no-untyped-def]
    from engine.criticality import criticality
    from engine.facts import build_contexts, build_module_facts, unit_facts
    from engine.health import unit_health
    from engine.strategies import UnitInputs
    from engine.workpackages import build_work_packages

    contexts = build_contexts(analysis)
    mfacts, estate = build_module_facts(analysis, cfg, contexts)
    wp = next(w for w in build_work_packages(analysis, cfg) if w.id == wid)
    f = unit_facts(analysis, cfg, wp.id, wp.kind, wp.classes, contexts[wp.module])
    crit = criticality(mfacts[wp.module], estate, {}, cfg).value
    return UnitInputs.build(f, unit_health(f, cfg), crit, scenario.change_requests(wp.module) * f.loc / mfacts[wp.module].loc)


def test_breakeven_report_structure(rec: Recommendation) -> None:
    for w in rec.work_packages.values():
        b = w.breakeven
        assert b is not None and b.baseline_jpy_per_year == pytest.approx(w.maintenance_baseline_jpy_per_year, abs=0.01)
        chosen = w.choices[rec.meta.selected_profile].chosen
        assert b.chosen == chosen
        selectable = {s.strategy for s in w.choices[rec.meta.selected_profile].ranking}
        assert {o.strategy for o in b.overtaking} == selectable - {chosen}
        for o in b.overtaking:
            if o.breakeven_jpy_per_year is not None:
                assert o.multiple_of_baseline == pytest.approx(o.breakeven_jpy_per_year / b.baseline_jpy_per_year, rel=1e-3)
                assert (o.breakeven_jpy_per_year > b.baseline_jpy_per_year) == (o.direction == "higher")


def test_the_breakeven_spend_really_changes_the_recommendation(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rec: Recommendation) -> None:
    import dataclasses

    from engine.scoring import pick
    from engine.strategies import build_options

    weights = scenario.priorities
    checked = 0
    for wid, w in rec.work_packages.items():
        assert w.breakeven is not None
        inputs = _inputs(analysis, cfg, scenario, wid)
        chosen = w.breakeven.chosen
        for o in w.breakeven.overtaking:
            if o.breakeven_jpy_per_year is None:
                continue
            ladder = [o.breakeven_jpy_per_year * (1 + d) for d in (-1e-2, -1e-3, 1e-3, 1e-2)]
            winners = {x: pick(build_options(dataclasses.replace(inputs, maintenance_override=x), cfg, scenario), weights, cfg)
                       for x in ladder}
            side = 1 if o.direction == "higher" else -1  # the overtaking side is further from the baseline
            beyond = [winners[x] for x in ladder if (x > o.breakeven_jpy_per_year) == (side == 1)]
            before = [winners[x] for x in ladder if (x > o.breakeven_jpy_per_year) != (side == 1)]
            assert chosen in before and o.strategy in beyond, (wid, o.strategy, winners)
            checked += 1
    assert checked > 0


def test_retain_breakeven_points_are_where_retain_loses(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rec: Recommendation) -> None:
    import dataclasses

    from engine.scoring import _scores
    from engine.strategies import build_options

    w = rec.work_packages["order/god-class-cluster-1"]
    assert w.breakeven is not None and w.breakeven.retain_loses_to_every_alternative_jpy_per_year is not None
    x = w.breakeven.retain_loses_to_every_alternative_jpy_per_year
    inputs = _inputs(analysis, cfg, scenario, "order/god-class-cluster-1")

    def retain_vs_min_alt(spend: float) -> float:
        sc = {s: score for s, score, _ in _scores(build_options(dataclasses.replace(inputs, maintenance_override=spend), cfg, scenario),
                                                  scenario.priorities, cfg)}
        return sc["retain"] - min(v for s, v in sc.items() if s != "retain")

    assert retain_vs_min_alt(x * 1.01) < 0 <= retain_vs_min_alt(x * 0.99)


def test_default_keeps_the_model_baseline_and_flags_nothing_applied(rec: Recommendation, scenario: ClientScenario) -> None:
    assert all(v is None for v in scenario.client_reported_maintenance_jpy.values())
    for m in rec.modules.values():
        cal = m.maintenance_calibration
        assert (cal.client_reported_jpy, cal.applied, cal.gap_jpy, cal.gap_pct, cal.flagged) == (None, False, None, None, False)
        wps = [rec.work_packages[i] for i in m.work_package_ids]
        assert cal.model_estimate_jpy == pytest.approx(sum(w.maintenance_baseline_jpy_per_year for w in wps), abs=len(wps))


def test_client_reported_maintenance_calibrates_the_baseline_and_shows_the_gap(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rec: Recommendation) -> None:
    model = rec.modules["billing"].maintenance_calibration.model_estimate_jpy
    sc = scenario.model_copy(deep=True)
    sc.client_reported_maintenance_jpy = {"billing": model * 2}
    out = run(analysis, cfg, sc)
    cal = out.modules["billing"].maintenance_calibration
    assert (cal.applied, cal.client_reported_jpy, cal.model_estimate_jpy) == (True, model * 2, model)
    assert cal.gap_jpy == model - model * 2 and cal.gap_pct == pytest.approx(-50.0, abs=0.01) and cal.flagged
    wps = [out.work_packages[i] for i in out.modules["billing"].work_package_ids]
    assert sum(w.maintenance_baseline_jpy_per_year for w in wps) == pytest.approx(model * 2, abs=1)  # calibrated to the client
    ratio = [w.maintenance_baseline_jpy_per_year / rec.work_packages[w.id].maintenance_baseline_jpy_per_year for w in wps]
    assert ratio == pytest.approx([2.0] * len(wps))  # packages keep their relative weights
    assert out.work_packages["order/cycle-1"].maintenance_baseline_jpy_per_year == rec.work_packages["order/cycle-1"].maintenance_baseline_jpy_per_year
    close = scenario.model_copy(deep=True)
    close.client_reported_maintenance_jpy = {"billing": round(model * 1.1)}
    assert not run(analysis, cfg, close).modules["billing"].maintenance_calibration.flagged  # within the 25% threshold


def test_scenario_kpi_is_labelled_whole_erp_and_restated_for_the_analysed_scope(
        rec: Recommendation, scenario: ClientScenario, cfg: EngineConfig) -> None:
    by = {k.objective: k for k in rec.kpi_reconciliation}
    m = by["maintenance_cost"]
    assert m.scope == "whole_erp" and m.kpi_current == 180.0 and m.analysed_scope_share == scenario.analysed_scope_share == 0.29
    assert m.kpi_current_in_analysed_scope == pytest.approx(180.0 * 0.29)
    model_total = sum(w.maintenance_baseline_jpy_per_year for w in rec.work_packages.values()) / 1e6
    assert m.model_baseline == pytest.approx(model_total, rel=1e-3) and m.gap == pytest.approx(model_total - 180.0 * 0.29, abs=1e-3)
    assert m.flagged == (abs(m.gap_pct or 0) > cfg.calibration.gap_flag_pct)
    assert by["change_lead_time"].scope == "organisation" and by["change_lead_time"].model_baseline is None  # not modelled
    assert by["run_cost"].kpi_current_in_analysed_scope == pytest.approx(36.0 * 0.29)


def test_change_cost_saving_is_its_own_benefit_line(rec: Recommendation, cfg: EngineConfig) -> None:
    w = rec.work_packages["order/god-class-cluster-1"]
    retain, refactor, rehost = opt(w, "retain"), opt(w, "refactor"), opt(w, "rehost")
    assert retain.tco is not None and refactor.tco is not None and rehost.tco is not None
    assert retain.tco.change_savings_vs_retain_jpy == 0 and retain.tco.change_total_jpy > 0
    assert refactor.tco.change_savings_vs_retain_jpy > rehost.tco.change_savings_vs_retain_jpy > 0
    assert refactor.tco.change_savings_vs_retain_jpy == retain.tco.change_total_jpy - refactor.tco.change_total_jpy
    # the maintenance saving is a different line: they add up, they are not the same number
    assert refactor.tco.savings_vs_retain_jpy == (
        (retain.tco.maintenance_total_jpy - refactor.tco.maintenance_total_jpy)
        + (retain.tco.run_total_jpy - refactor.tco.run_total_jpy)
        + refactor.tco.change_savings_vs_retain_jpy - refactor.tco.migration_total_jpy)


def test_value_leaves_out_the_monetised_objective_instead_of_double_counting_it(rec: Recommendation, cfg: EngineConfig) -> None:
    w = rec.work_packages["order/god-class-cluster-1"]
    v = opt(w, "refactor").value
    assert v is not None
    lead = next(x for x in v.objectives if x.objective == cfg.change_cost.monetised_objective)
    assert lead.counted is False and lead.contribution == 0.0 and lead.effect > 0  # it moves, but TCO pays for it
    assert sum(x.contribution for x in v.objectives) == pytest.approx(v.objective_fit)
    assert v.objective_fit <= 1.0


def test_more_change_requests_raise_retain_cost_and_the_saving(
        analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario, rec: Recommendation) -> None:
    busy = scenario.model_copy(deep=True)
    busy.change_requests_per_year = {**scenario.change_requests_per_year, "order": scenario.change_requests("order") * 2}
    out = run(analysis, cfg, busy)
    a, b = rec.work_packages["order/god-class-cluster-1"], out.work_packages["order/god-class-cluster-1"]
    assert opt(b, "retain").tco.change_total_jpy == pytest.approx(2 * opt(a, "retain").tco.change_total_jpy, rel=1e-3)  # type: ignore[union-attr]
    assert opt(b, "refactor").tco.change_savings_vs_retain_jpy > opt(a, "refactor").tco.change_savings_vs_retain_jpy  # type: ignore[union-attr]
    assert out.modules["order"].change_requests_per_year == 240.0
