"""Effort, cost, duration, risk and long-term value per modernization strategy, with eligibility rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.config import EngineConfig, Strategy
from engine.facts import ModuleFacts
from engine.schema import Component, Criticality, EffortLine, ModuleHealth, StrategyOption


@dataclass
class ModuleInputs:
    """Everything the strategy model needs about one module (already computed, assumption-free)."""

    facts: ModuleFacts
    health_score: float
    complexity_norm: float  # 0..1 LOC-weighted complexity percentile
    test_gap: float  # 0 (well tested) .. 1 (no tests)
    cycles_norm: float
    criticality: int

    @classmethod
    def build(cls, facts: ModuleFacts, health: ModuleHealth, crit: Criticality) -> ModuleInputs:
        norm = {c.key: c.normalized for c in health.components}
        return cls(facts=facts, health_score=health.score, complexity_norm=facts.complexity_pct / 100.0,
                   test_gap=norm["test_evidence"], cycles_norm=norm["cycles"], criticality=crit.value)


@dataclass
class OptionCalc:
    strategy: Strategy
    eligible: bool
    reason: str | None = None
    multipliers: dict[str, float] = field(default_factory=dict)
    lines: list[EffortLine] = field(default_factory=list)
    effort_days: float | None = None
    cost_jpy: int | None = None
    duration_months: float | None = None
    team_size: float | None = None
    risk_score: float | None = None
    base_risk: float | None = None
    risk_parts: list[Component] = field(default_factory=list)
    long_term_value: float | None = None
    debt_reduction: float | None = None
    burden: float | None = None


def ineligible_reason(strategy: Strategy, f: ModuleFacts) -> str | None:
    """retire is only allowed when nothing points into the module on ANY inbound type."""
    if strategy == "retire" and not f.is_unused:
        return (f"module is in use: {f.java_cross_module_fan_in} cross-module Java references, "
                f"{f.service_fan_in} service definitions and {f.controller_fan_in} controller events point into it")
    return None


def _effort_lines(s: Strategy, m: ModuleInputs, cfg: EngineConfig) -> tuple[dict[str, float], list[EffortLine]]:
    f = m.facts
    base = cfg.base_days_per_kloc[s]
    cm = 1.0 + (cfg.complexity_multiplier.max - 1.0) * m.complexity_norm * cfg.complexity_multiplier.sensitivity[s]
    overhead = cfg.test_overhead.base[s] * (1.0 + cfg.test_overhead.untested_extra * m.test_gap)
    buffer = cfg.coverage_uncertainty_buffer[f.confidence]
    lines = [EffortLine(
        label="Core work", days=round(f.kloc * base * cm * (1.0 + overhead) * buffer, 4),
        formula=f"KLOC {f.kloc:.3f} x {base:g} days/KLOC x complexity {cm:.4f} x (1 + test overhead {overhead:.4f}) "
                f"x uncertainty buffer {buffer:g} ({f.confidence} confidence)")]
    if s == "rearchitect" and not f.has_tests:
        lines.append(EffortLine(
            label="Build safety-net tests first", days=round(f.kloc * cfg.safety_net_days_per_kloc * buffer, 4),
            formula=f"KLOC {f.kloc:.3f} x {cfg.safety_net_days_per_kloc:g} days/KLOC x buffer {buffer:g}; "
                    "rearchitect needs test evidence and this module has none"))
    return {"complexity_multiplier": cm, "test_overhead": overhead, "uncertainty_buffer": buffer}, lines


def _risk(s: Strategy, m: ModuleInputs, cfg: EngineConfig) -> tuple[float, list[Component]]:
    w = cfg.risk.factor_weights
    measures = {"health": 1.0 - m.health_score / 100.0, "criticality": (m.criticality - 1) / 2.0,
                "tests": m.test_gap, "cycles": m.cycles_norm,
                "confidence": cfg.risk.confidence_gap[m.facts.confidence]}
    parts = [Component(key=k, measure=round(v, 6), weight=w[k], contribution=round(w[k] * v, 4))
             for k, v in measures.items()]
    exposure = sum(p.contribution for p in parts)
    return round(min(100.0, cfg.risk.base[s] * (1.0 + cfg.risk.exposure_gain * exposure)), 4), parts


def _value(s: Strategy, m: ModuleInputs, cfg: EngineConfig) -> tuple[float, float, float]:
    rule = cfg.long_term_value
    maintenance = min(100.0, 100.0 * m.facts.kloc / rule.maintenance_kloc_cap)
    burden = round(rule.debt_weight * (100.0 - m.health_score) + (1.0 - rule.debt_weight) * maintenance, 4)
    reduction = rule.debt_reduction[s]
    return round(reduction * burden, 4), reduction, burden


def build_option(s: Strategy, m: ModuleInputs, cfg: EngineConfig) -> OptionCalc:
    reason = ineligible_reason(s, m.facts)
    if reason:
        return OptionCalc(strategy=s, eligible=False, reason=reason)
    mult, lines = _effort_lines(s, m, cfg)
    effort = round(sum(line.days for line in lines), 4)
    risk, parts = _risk(s, m, cfg)
    value, reduction, burden = _value(s, m, cfg)
    team = cfg.team_size[s]
    return OptionCalc(
        strategy=s, eligible=True, multipliers=mult, lines=lines, effort_days=effort,
        cost_jpy=round(effort * cfg.daily_rate_jpy), team_size=team,
        duration_months=round(effort / (team * cfg.working_days_per_month), 4), risk_score=risk,
        base_risk=cfg.risk.base[s], risk_parts=parts, long_term_value=value, debt_reduction=reduction, burden=burden)


def build_options(m: ModuleInputs, cfg: EngineConfig) -> list[OptionCalc]:
    return [build_option(s, m, cfg) for s in cfg.strategies]


def to_schema(o: OptionCalc) -> StrategyOption:
    return StrategyOption(
        strategy=o.strategy, eligible=o.eligible, ineligible_reason=o.reason, multipliers=o.multipliers,
        effort_lines=o.lines, effort_days=o.effort_days, cost_jpy=o.cost_jpy, duration_months=o.duration_months,
        team_size=o.team_size, risk_score=o.risk_score, base_risk=o.base_risk, risk_components=o.risk_parts,
        long_term_value=o.long_term_value, debt_reduction=o.debt_reduction, burden=o.burden)
