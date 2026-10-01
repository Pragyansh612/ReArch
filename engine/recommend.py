"""Orchestrates Phase 3: health, criticality, strategy options, priorities, sensitivity, estate totals."""

from __future__ import annotations

from analyzer.schema import AnalysisResult
from engine.config import (
    DEFAULT_OVERRIDES,
    EngineConfig,
    Override,
    Priorities,
    load_engine_config,
    load_overrides,
    parse_profile,
)
from engine.criticality import criticality
from engine.facts import build_facts
from engine.health import hotspots, module_health
from engine.schema import ModuleReport, ProfileTotals, Recommendation, RecommendationMeta
from engine.scoring import choose
from engine.sensitivity import find_flips
from engine.strategies import ModuleInputs, OptionCalc, build_options, to_schema

NOTES = [
    "ILLUSTRATIVE ASSUMPTIONS: every rate, multiplier and weight comes from config/assumptions.yaml and is not market data.",
    ("Each criterion is scored on an absolute 0..1 scale (cost and duration against configured ceilings, risk and value "
     "on their 0-100 scales), so module size, health and the daily rate all influence the result."),
    "Cost and speed are both functions of effort and tend to move together.",
    "Estate duration adds module durations (one shared programme team, sequential). Phase 4 arranges waves and parallelism.",
    "Business criticality is a proposal from usage and data-write intensity; the consultant confirms or overrides it.",
    "Effort uses the analysed Java only; Groovy/XML logic is covered by the uncertainty buffer, not measured.",
]


def _estate(profile: str, weights: Priorities, reports: dict[str, ModuleReport],
            calc: dict[str, list[OptionCalc]]) -> ProfileTotals:
    chosen = {m: r.choices[profile].chosen for m, r in reports.items()}
    picked = [next(o for o in calc[m] if o.strategy == chosen[m]) for m in reports]
    return ProfileTotals(
        profile=profile, weights=weights, strategy_by_module=chosen,
        total_effort_days=round(sum(o.effort_days or 0.0 for o in picked), 4),
        total_cost_jpy=sum(o.cost_jpy or 0 for o in picked),
        total_duration_months=round(sum(o.duration_months or 0.0 for o in picked), 4),
        close_calls=sorted(m for m, r in reports.items() if r.choices[profile].close_call))


def recommend(result: AnalysisResult, cfg: EngineConfig | None = None, profile: str | None = None,
              overrides: dict[str, Override] | None = None, sensitivity: bool = True) -> Recommendation:
    cfg = cfg or load_engine_config()
    selected_name, selected = parse_profile(profile or cfg.priorities.default, cfg)
    profiles = dict(cfg.priorities.presets)
    profiles.setdefault(selected_name, selected)
    overrides = load_overrides(result.meta.name, DEFAULT_OVERRIDES) if overrides is None else overrides
    unknown = set(overrides) - set(result.modules)
    if unknown:
        raise ValueError(f"criticality overrides name unknown modules {sorted(unknown)}; known: {sorted(result.modules)}")
    facts, estate = build_facts(result, cfg)
    reports: dict[str, ModuleReport] = {}
    calc: dict[str, list[OptionCalc]] = {}
    for name, f in facts.items():
        health = module_health(f, estate, cfg)
        crit = criticality(f, estate, overrides, cfg)
        inputs = ModuleInputs.build(f, health, crit)
        calc[name] = build_options(inputs, cfg)
        choices = {p: choose(calc[name], w, p, cfg) for p, w in profiles.items()}
        reports[name] = ModuleReport(
            module=name, loc=f.loc, kloc=round(f.kloc, 4), health=health, criticality=crit, confidence=f.confidence,  # type: ignore[arg-type]
            java_share=f.java_share,
            inbound_references={"java_cross_module": f.java_cross_module_fan_in, "service": f.service_fan_in,
                                "controller": f.controller_fan_in},
            options=[to_schema(o) for o in calc[name]], choices=choices,
            sensitivity=find_flips(inputs, cfg, selected, choices[selected_name].chosen) if sensitivity else [])
    return Recommendation(
        meta=RecommendationMeta(analysis_name=result.meta.name, analyzer=result.meta.analyzer,
                                selected_profile=selected_name, notes=NOTES),
        assumptions={"illustrative": True, "notice": NOTES[0], "config": cfg.model_dump(mode="json")},
        modules=reports, hotspots=hotspots(result, cfg),
        estate={p: _estate(p, w, reports, calc) for p, w in profiles.items()})
