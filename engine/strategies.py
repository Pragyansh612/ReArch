"""Per work package: effort, migration cost, TCO, risk, value and feasibility for every strategy, incl. retain."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from engine import tco as tco_mod
from engine.config import EngineConfig, Strategy
from engine.facts import UnitFacts
from engine.scenario import ClientScenario
from engine.schema import (
    Component,
    EffortLine,
    ModuleHealth,
    ObjectiveContribution,
    StrategyOption,
    Tco,
    ValueBreakdown,
)


@dataclass
class UnitInputs:
    """Everything the strategy model needs about one unit (already computed, assumption-free)."""

    facts: UnitFacts
    health_score: float
    complexity_norm: float  # 0..1 LOC-weighted complexity percentile
    test_gap: float  # 0 (well tested) .. 1 (no tests)
    cycles_norm: float
    criticality: int
    change_requests: float = 0.0  # this unit's share of its module's change requests per year
    maintenance_override: float | None = None  # yearly maintenance in JPY, replacing the model's estimate

    @classmethod
    def build(cls, facts: UnitFacts, health: ModuleHealth, criticality: int, change_requests: float = 0.0,
              maintenance_override: float | None = None) -> UnitInputs:
        norm = {c.key: c.normalized for c in health.components}
        return cls(facts=facts, health_score=health.score, complexity_norm=facts.complexity_pct / 100.0,
                   test_gap=norm["test_evidence"], cycles_norm=norm["cycles"], criticality=criticality,
                   change_requests=change_requests, maintenance_override=maintenance_override)


@dataclass
class OptionCalc:
    strategy: Strategy
    eligible: bool
    reason: str | None = None
    feasible: bool = True
    infeasible: list[str] = field(default_factory=list)
    multipliers: dict[str, float] = field(default_factory=dict)
    lines: list[tuple[str, float, dict[str, float]]] = field(default_factory=list)
    effort_days: float = 0.0
    cost_jpy: int = 0
    duration_months: float = 0.0
    team_size: float | None = None
    cutover: tuple[str, int, float] = ("none", 0, 0.0)  # (approach, events, hours per event)
    risk_score: float = 0.0
    base_risk: float | None = None
    risk_parts: list[tuple[str, float, float, float]] = field(default_factory=list)
    value: float = 0.0
    value_parts: dict[str, float] = field(default_factory=dict)
    objective_parts: list[tuple[str, float, float, float, bool]] = field(default_factory=list)
    rows: list[tco_mod.Row] = field(default_factory=list)
    maintenance_year: float = 0.0
    run_year: float = 0.0
    change_year: float = 0.0
    steady: tuple[int, int, int] = (0, 0, 0)
    tco_jpy: int = 0

    @property
    def selectable(self) -> bool:
        return self.eligible and self.feasible


def ineligible_reason(strategy: Strategy, f: UnitFacts) -> str | None:
    """retire is only allowed when nothing points into the unit on ANY inbound type."""
    if strategy == "retire" and not f.is_unused:
        return (f"in use: {f.java_inbound} Java references from outside, {f.service_fan_in} service definitions "
                f"and {f.controller_fan_in} controller events point into it")
    return None


def _risk_parts(m: UnitInputs, cfg: EngineConfig) -> list[tuple[str, float, float, float]]:
    w = cfg.risk.factor_weights
    measures = {"health": 1.0 - m.health_score / 100.0, "criticality": (m.criticality - 1) / 2.0,
                "tests": m.test_gap, "cycles": m.cycles_norm,
                "confidence": cfg.risk.confidence_gap[m.facts.confidence]}
    return [(k, round(v, 6), w[k], round(w[k] * v, 4)) for k, v in measures.items()]


def _burden(m: UnitInputs, cfg: EngineConfig) -> float:
    rule = cfg.long_term_value
    maintenance = min(100.0, 100.0 * m.facts.kloc / rule.maintenance_kloc_cap)
    return round(rule.debt_weight * (100.0 - m.health_score) + (1.0 - rule.debt_weight) * maintenance, 4)


def objective_fit(strategy: Strategy, cfg: EngineConfig, scenario: ClientScenario) -> list[tuple[str, float, float, float, bool]]:
    """(objective, weight, effect, contribution, counted). The objective monetised in TCO (change cost) is not counted and
    the counted weights are renormalised, so contributions sum to the fit (0..1)."""
    effects = cfg.long_term_value.objective_effect[strategy]
    skip = cfg.change_cost.monetised_objective
    counted_weight = sum(o.weight for o in scenario.objectives if o.id != skip)
    return [(o.id, o.weight, effects[o.id],
             round(o.weight * effects[o.id] / counted_weight, 6) if o.id != skip and counted_weight else 0.0, o.id != skip)
            for o in scenario.objectives]


def _effort(s: Strategy, m: UnitInputs, cfg: EngineConfig) -> tuple[dict[str, float], list[tuple[str, float, dict[str, float]]]]:
    f = m.facts
    base = cfg.base_days_per_kloc[s]
    cm = 1.0 + (cfg.complexity_multiplier.max - 1.0) * m.complexity_norm * cfg.complexity_multiplier.sensitivity[s]
    overhead = cfg.test_overhead.base[s] * (1.0 + cfg.test_overhead.untested_extra * m.test_gap)
    buffer = cfg.coverage_uncertainty_buffer[f.confidence]
    parts = {"kloc": f.kloc, "base": base, "complexity": cm, "overhead": overhead, "buffer": buffer}
    lines = [("Core work", round(f.kloc * base * cm * (1.0 + overhead) * buffer, 4), parts)]
    if s == "rearchitect" and not f.has_tests:
        lines.append(("Build safety-net tests first",
                      round(f.kloc * cfg.safety_net_days_per_kloc * buffer, 4),
                      {"kloc": f.kloc, "rate": cfg.safety_net_days_per_kloc, "buffer": buffer}))
    if cfg.cutover.approach[s] == "incremental":
        lines.append(("Parallel run of old and new", round(lines[0][1] * cfg.cutover.incremental.parallel_run_effort_share, 4),
                      {"core": lines[0][1], "share": cfg.cutover.incremental.parallel_run_effort_share}))
    return {"complexity_multiplier": cm, "test_overhead": overhead, "uncertainty_buffer": buffer}, lines


def model_maintenance(m: UnitInputs, cfg: EngineConfig) -> float:
    """The model's own yearly maintenance estimate for the unit: worse health costs more to maintain."""
    t = cfg.tco
    return (m.facts.kloc * t.maintenance_days_per_kloc_year
            * (1.0 + t.debt_maintenance_penalty * (1.0 - m.health_score / 100.0)) * cfg.daily_rate_jpy)


def _baseline(m: UnitInputs, cfg: EngineConfig) -> tuple[float, float, float]:
    maintenance = model_maintenance(m, cfg) if m.maintenance_override is None else m.maintenance_override
    c = cfg.change_cost
    change = m.change_requests * c.base_days_per_change * (1.0 + c.health_penalty * (1.0 - m.health_score / 100.0)) * cfg.daily_rate_jpy
    return maintenance, m.facts.kloc * cfg.tco.run_cost_jpy_per_kloc_year, change


def change_factor(m: UnitInputs, cfg: EngineConfig, reduction: float) -> float:
    """Post-migration change cost relative to today: the multiplier uses the RESIDUAL debt (1 - reduction)."""
    c = cfg.change_cost
    before = 1.0 + c.health_penalty * (1.0 - m.health_score / 100.0)
    after = 1.0 + c.health_penalty * (1.0 - reduction) * (1.0 - m.health_score / 100.0)
    return after / before


def cutover_plan(s: Strategy, kloc: float, cfg: EngineConfig) -> tuple[str, int, float]:
    """(approach, number of cutover events, hours per event)."""
    approach = cfg.cutover.approach[s]
    if approach == "big_bang":
        rule = cfg.cutover.big_bang
        return approach, 1, round(rule.base_hours.get(s, 0.0) + rule.hours_per_kloc * kloc, 4)
    if approach == "incremental":
        rule_i = cfg.cutover.incremental
        return approach, max(1, math.ceil(kloc / rule_i.slice_kloc)), rule_i.hours_per_slice
    return "none", 0, 0.0


def _feasibility(s: Strategy, m: UnitInputs, cost: int, cutover: tuple[str, int, float], scenario: ClientScenario) -> list[str]:
    reasons: list[str] = []
    c = scenario.constraints
    if cost > c.budget_ceiling_jpy:
        reasons.append(f"migration cost JPY {cost:,} exceeds the client's budget ceiling JPY {c.budget_ceiling_jpy:,}")
    limit = c.max_cutover_downtime_hours.get(m.facts.module)
    approach, events, hours = cutover
    if limit is not None and hours > limit:
        what = "the single big-bang cutover" if approach == "big_bang" else f"each of {events} cutover slices"
        reasons.append(f"{what} needs {hours:g} h, above the client's per-event maximum of {limit:g} h for {m.facts.module}")
    return reasons


def build_retain(m: UnitInputs, cfg: EngineConfig, scenario: ClientScenario) -> OptionCalc:
    """Do nothing: no migration, today's maintenance, run and change cost for the whole horizon, no change risk."""
    maintenance, run, change = _baseline(m, cfg)
    parts = _risk_parts(m, cfg)
    rows = tco_mod.tco_rows(maintenance_year=maintenance, run_year=run, change_year=change, migration_cost=0, duration_months=0.0,
                            reduction=0.0, run_factor=1.0, change_factor=1.0, horizon=scenario.constraints.planning_horizon_years)
    return OptionCalc(
        strategy="retain", eligible=True, risk_score=round(min(100.0, cfg.retain.risk_scale * 100.0 * sum(p[3] for p in parts)), 4),
        risk_parts=parts, value=0.0,
        value_parts={"debt_reduction": 0.0, "burden": _burden(m, cfg), "criticality_weight": cfg.long_term_value.criticality_weight[m.criticality],
                     "objective_fit": 0.0, "uncapped": 0.0},
        objective_parts=objective_fit("retain", cfg, scenario), rows=rows, maintenance_year=maintenance, run_year=run,
        change_year=change, steady=(round(maintenance), round(run), round(change)), tco_jpy=tco_mod.tco_of(rows))


def build_option(s: Strategy, m: UnitInputs, cfg: EngineConfig, scenario: ClientScenario, retain: OptionCalc) -> OptionCalc:
    reason = ineligible_reason(s, m.facts)
    if reason:
        return OptionCalc(strategy=s, eligible=False, reason=reason)
    mult, lines = _effort(s, m, cfg)
    effort = round(sum(line[1] for line in lines), 4)
    cost = round(effort * cfg.daily_rate_jpy)
    team = cfg.team_size[s]
    duration = round(effort / (team * cfg.working_days_per_month), 4)
    parts = _risk_parts(m, cfg)
    risk = round(min(100.0, cfg.risk.base[s] * (1.0 + cfg.risk.exposure_gain * sum(p[3] for p in parts))), 4)
    rule = cfg.long_term_value
    burden, reduction = _burden(m, cfg), rule.debt_reduction[s]
    objectives = objective_fit(s, cfg, scenario)
    fit = sum(o[3] for o in objectives)
    cw = rule.criticality_weight[m.criticality]
    uncapped = round(reduction * burden * cw * fit, 4)
    run_factor, c_factor = cfg.tco.residual_run_cost[s], change_factor(m, cfg, reduction)
    rows = tco_mod.tco_rows(
        maintenance_year=retain.maintenance_year, run_year=retain.run_year, change_year=retain.change_year,
        migration_cost=cost, duration_months=duration, reduction=reduction, run_factor=run_factor, change_factor=c_factor,
        horizon=scenario.constraints.planning_horizon_years)
    cutover = cutover_plan(s, m.facts.kloc, cfg)
    infeasible = _feasibility(s, m, cost, cutover, scenario)
    return OptionCalc(
        strategy=s, eligible=True, feasible=not infeasible, infeasible=infeasible, multipliers=mult, lines=lines,
        effort_days=effort, cost_jpy=cost, duration_months=duration, team_size=team, cutover=cutover,
        risk_score=risk, base_risk=cfg.risk.base[s], risk_parts=parts,
        value=min(100.0, uncapped), value_parts={"debt_reduction": reduction, "burden": burden, "criticality_weight": cw,
                                                 "objective_fit": fit, "uncapped": uncapped},
        objective_parts=objectives, rows=rows, maintenance_year=retain.maintenance_year, run_year=retain.run_year,
        change_year=retain.change_year,
        steady=(round(retain.maintenance_year * (1.0 - reduction)), round(retain.run_year * run_factor),
                round(retain.change_year * c_factor)),
        tco_jpy=tco_mod.tco_of(rows))


def build_options(m: UnitInputs, cfg: EngineConfig, scenario: ClientScenario) -> list[OptionCalc]:
    retain = build_retain(m, cfg, scenario)
    return [retain if s == "retain" else build_option(s, m, cfg, scenario, retain) for s in cfg.strategies]


def _formula(parts: dict[str, float]) -> str:
    if "complexity" in parts:
        return (f"KLOC {parts['kloc']:.3f} x {parts['base']:g} days/KLOC x complexity {parts['complexity']:.4f} "
                f"x (1 + test overhead {parts['overhead']:.4f}) x uncertainty buffer {parts['buffer']:g}")
    if "share" in parts:
        return (f"{parts['share']:g} x core work {parts['core']:g} days: old and new run side by side while slices "
                "are cut over (incremental/strangler approach)")
    return (f"KLOC {parts['kloc']:.3f} x {parts['rate']:g} days/KLOC x buffer {parts['buffer']:g}; rearchitect needs "
            "test evidence and this unit has none")


def to_schema(o: OptionCalc, discount_rate: float, retain: OptionCalc, criticality: int) -> StrategyOption:
    if not o.eligible:
        return StrategyOption(strategy=o.strategy, eligible=False, ineligible_reason=o.reason)
    tco = tco_mod.to_model(o.rows, maintenance_year=o.maintenance_year, run_year=o.run_year, change_year=o.change_year,
                           steady=o.steady, discount_rate=discount_rate,
                           retain_rows=None if o.strategy == "retain" else retain.rows)
    vp = o.value_parts
    value = ValueBreakdown(
        debt_reduction=vp["debt_reduction"], burden=vp["burden"], criticality=criticality,
        criticality_weight=vp["criticality_weight"], objective_fit=vp["objective_fit"], uncapped=vp["uncapped"],
        value=o.value, objectives=[ObjectiveContribution(objective=i, weight=w, effect=e, contribution=c, counted=n)
                                   for i, w, e, c, n in o.objective_parts])
    approach, events, hours = o.cutover
    return StrategyOption(
        strategy=o.strategy, eligible=True, feasible=o.feasible, infeasible_reasons=o.infeasible,
        multipliers=o.multipliers, effort_lines=[EffortLine(label=lbl, days=days, formula=_formula(p))
                                                 for lbl, days, p in o.lines],
        effort_days=o.effort_days, migration_cost_jpy=o.cost_jpy, duration_months=o.duration_months,
        team_size=o.team_size, cutover_approach=approach, cutover_events=events, cutover_hours_per_event=hours,
        cutover_total_hours=round(events * hours, 4), risk_score=o.risk_score, base_risk=o.base_risk,
        risk_components=[Component(key=k, measure=m, weight=w, contribution=c) for k, m, w, c in o.risk_parts],
        value=value, tco=tco)


__all__ = ["OptionCalc", "Tco", "UnitInputs", "build_options", "to_schema"]
