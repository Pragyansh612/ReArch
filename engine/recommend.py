"""Orchestrates the engine: health, criticality, work packages, options, priorities, sensitivity, rollups."""

from __future__ import annotations

import dataclasses

from analyzer.schema import AnalysisResult
from engine.breakeven import compute_breakeven
from engine.config import EngineConfig, Override, Priorities, load_engine_config, parse_profile
from engine.criticality import criticality
from engine.facts import EstateFacts, UnitFacts, build_contexts, build_module_facts, unit_facts
from engine.health import hotspots, unit_health
from engine.scenario import ClientScenario, check_consistency, load_scenario
from engine.schema import (
    KpiReconciliation,
    MaintenanceCalibration,
    ModuleReport,
    ModuleRollup,
    OutdatedDependencies,
    ProfileTotals,
    Recommendation,
    RecommendationMeta,
    WorkPackageReport,
)
from engine.scoring import choose
from engine.sensitivity import find_flips
from engine.strategies import OptionCalc, UnitInputs, build_options, model_maintenance, to_schema
from engine.workpackages import WorkPackage, build_work_packages

CLIENT_PROFILE = "client_scenario"
NOTES = [
    "ILLUSTRATIVE ASSUMPTIONS: every rate, multiplier and weight comes from config/assumptions.yaml and is not market data.",
    "FICTIONAL CLIENT: constraints, KPIs, priorities and criticality overrides come from config/client_scenario.yaml.",
    ("Strategies are chosen per work package (class cycles, extreme god classes with their satellites, module remainders), "
     "so a module can mix strategies. Module figures are sums over its packages."),
    "Cost is the planning-horizon TCO scored against doing nothing (retain); migration cost is shown separately.",
    "Options that break a client constraint are shown as infeasible with the reason; they are never silently dropped.",
    "Estate duration adds package durations (one shared programme team, sequential). Phase 4 arranges waves and parallelism.",
    "Effort uses the analysed Java only; Groovy/XML logic is covered by the uncertainty buffer, not measured.",
]


def _rollup(profile: str, wps: list[WorkPackageReport], calc: dict[str, list[OptionCalc]]) -> ModuleRollup:
    picked = {w.id: next(o for o in calc[w.id] if o.strategy == w.choices[profile].chosen) for w in wps}
    retain = {w.id: next(o for o in calc[w.id] if o.strategy == "retain") for w in wps}
    return ModuleRollup(
        profile=profile, strategy_by_work_package={w.id: w.choices[profile].chosen for w in wps}, loc=sum(w.loc for w in wps),
        effort_days=round(sum(picked[w.id].effort_days for w in wps), 4),
        migration_cost_jpy=sum(picked[w.id].cost_jpy for w in wps), tco_jpy=sum(picked[w.id].tco_jpy for w in wps),
        retain_tco_jpy=sum(retain[w.id].tco_jpy for w in wps),
        duration_months=round(sum(picked[w.id].duration_months for w in wps), 4))


def _estate(profile: str, weights: Priorities, wps: list[WorkPackageReport], calc: dict[str, list[OptionCalc]],
            scenario: ClientScenario, discount: float) -> ProfileTotals:
    from engine import tco as tco_mod

    chosen = {w.id: w.choices[profile].chosen for w in wps}
    picked = [next(o for o in calc[w.id] if o.strategy == chosen[w.id]) for w in wps]
    retain = [next(o for o in calc[w.id] if o.strategy == "retain") for w in wps]
    migration = sum(o.cost_jpy for o in picked)
    npv_picked = sum(tco_mod.npv_of(o.rows, discount) for o in picked)
    npv_retain = sum(tco_mod.npv_of(o.rows, discount) for o in retain)
    mix: dict[str, int] = {}
    for s in chosen.values():
        mix[s] = mix.get(s, 0) + 1
    return ProfileTotals(
        profile=profile, weights=weights, strategy_by_work_package=chosen, strategy_mix=dict(sorted(mix.items())),
        total_effort_days=round(sum(o.effort_days for o in picked), 4), total_migration_cost_jpy=migration,
        total_tco_jpy=sum(o.tco_jpy for o in picked), retain_tco_jpy=sum(o.tco_jpy for o in retain),
        tco_savings_vs_retain_jpy=sum(r.tco_jpy for r in retain) - sum(o.tco_jpy for o in picked),
        npv_vs_retain_jpy=npv_retain - npv_picked, total_duration_months=round(sum(o.duration_months for o in picked), 4),
        budget_ceiling_jpy=scenario.constraints.budget_ceiling_jpy,
        within_budget=migration <= scenario.constraints.budget_ceiling_jpy,
        close_calls=sorted(w.id for w in wps if w.choices[profile].close_call))


def _wp_report(wp: WorkPackage, f: UnitFacts, inputs: UnitInputs, calc: list[OptionCalc], profiles: dict[str, Priorities],
               cfg: EngineConfig, scenario: ClientScenario, selected: tuple[str, Priorities], health: object,
               sensitivity: bool) -> WorkPackageReport:
    retain = next(o for o in calc if o.strategy == "retain")
    choices = {p: choose(calc, w, p, cfg) for p, w in profiles.items()}
    return WorkPackageReport(
        id=wp.id, module=wp.module, kind=wp.kind, name=wp.name, classes=wp.classes, cycle_modules=wp.cycle_modules,
        loc=f.loc, kloc=round(f.kloc, 4), health=health, confidence=f.confidence,  # type: ignore[arg-type]
        inbound_references={"java_from_outside": f.java_inbound, "service": f.service_fan_in, "controller": f.controller_fan_in},
        options=[to_schema(o, cfg.tco.discount_rate, retain, inputs.criticality) for o in calc], choices=choices,
        sensitivity=find_flips(inputs, cfg, scenario, selected[1], choices[selected[0]].chosen) if sensitivity else [],
        breakeven=compute_breakeven(inputs, cfg, scenario, selected[1], choices[selected[0]].chosen) if sensitivity else None,
        maintenance_baseline_jpy_per_year=retain.maintenance_year, change_requests_per_year=round(inputs.change_requests, 4))


def recommend(result: AnalysisResult, cfg: EngineConfig | None = None, profile: str | None = None,
              scenario: ClientScenario | None = None, overrides: dict[str, Override] | None = None,
              sensitivity: bool = True) -> Recommendation:
    cfg = cfg or load_engine_config()
    scenario = scenario or load_scenario()
    check_consistency(scenario, cfg)
    profiles = {**cfg.priorities.presets, CLIENT_PROFILE: scenario.priorities}
    selected_name, selected = parse_profile(profile or CLIENT_PROFILE, profiles)
    profiles.setdefault(selected_name, selected)
    overrides = scenario.overrides_for(result.meta.name) if overrides is None else overrides
    unknown = set(overrides) - set(result.modules)
    if unknown:
        raise ValueError(f"criticality overrides name unknown modules {sorted(unknown)}; known: {sorted(result.modules)}")

    contexts = build_contexts(result)
    module_facts, estate = build_module_facts(result, cfg, contexts)
    module_health = {m: unit_health(f, cfg) for m, f in module_facts.items()}
    crit = {m: criticality(f, estate, overrides, cfg) for m, f in module_facts.items()}

    packages = []
    for wp in build_work_packages(result, cfg):
        f = unit_facts(result, cfg, wp.id, wp.kind, wp.classes, contexts[wp.module])
        health = unit_health(f, cfg)
        share = f.loc / module_facts[wp.module].loc if module_facts[wp.module].loc else 0.0
        packages.append((wp, f, health, UnitInputs.build(f, health, crit[wp.module].value,
                                                         scenario.change_requests(wp.module) * share)))
    calibration: dict[str, MaintenanceCalibration] = {}
    for module in module_facts:
        members = [p for p in packages if p[0].module == module]
        model_total = sum(model_maintenance(p[3], cfg) for p in members)
        client = scenario.client_reported_maintenance_jpy.get(module)
        gap = None if client is None else round(model_total) - client
        gap_pct = None if client in (None, 0) or gap is None else round(100.0 * gap / client, 2)
        calibration[module] = MaintenanceCalibration(
            model_estimate_jpy=round(model_total), client_reported_jpy=client, applied=client is not None, gap_jpy=gap,
            gap_pct=gap_pct, flagged=gap_pct is not None and abs(gap_pct) > cfg.calibration.gap_flag_pct)
        if client is not None and model_total > 0:  # calibrate: spread the client's figure over packages in proportion
            for i, p in enumerate(packages):
                if p[0].module == module:
                    packages[i] = (*p[:3], dataclasses.replace(
                        p[3], maintenance_override=client * model_maintenance(p[3], cfg) / model_total))

    wp_reports: dict[str, WorkPackageReport] = {}
    calc: dict[str, list[OptionCalc]] = {}
    for wp, f, health, inputs in packages:
        calc[wp.id] = build_options(inputs, cfg, scenario)
        wp_reports[wp.id] = _wp_report(wp, f, inputs, calc[wp.id], profiles, cfg, scenario, (selected_name, selected),
                                       health, sensitivity)

    modules: dict[str, ModuleReport] = {}
    for name, f in module_facts.items():
        wps = [w for w in wp_reports.values() if w.module == name]
        modules[name] = ModuleReport(
            module=name, loc=f.loc, kloc=round(f.kloc, 4), health=module_health[name], criticality=crit[name],
            confidence=f.confidence, java_share=f.java_share,  # type: ignore[arg-type]
            maintenance_calibration=calibration[name], change_requests_per_year=scenario.change_requests(name),
            work_package_ids=[w.id for w in wps], rollups={p: _rollup(p, wps, calc) for p in profiles})
    return Recommendation(
        meta=RecommendationMeta(analysis_name=result.meta.name, analyzer=result.meta.analyzer, selected_profile=selected_name,
                                scenario_client=str(scenario.client.get("name", "")), notes=NOTES),
        assumptions={"illustrative": True, "notice": NOTES[0], "config": cfg.model_dump(mode="json")},
        scenario=scenario.model_dump(mode="json"), modules=modules, work_packages=wp_reports,
        hotspots=hotspots(result, cfg),
        estate={p: _estate(p, w, list(wp_reports.values()), calc, scenario, cfg.tco.discount_rate) for p, w in profiles.items()},
        estate_findings=_outdated(result, estate), kpi_reconciliation=_kpis(scenario, cfg, packages))


def _outdated(result: AnalysisResult, estate: EstateFacts) -> OutdatedDependencies:
    return OutdatedDependencies(
        declared=len(result.dependencies), checked=estate.checked_dependencies, unchecked=estate.unchecked_dependencies,
        outdated=estate.outdated_dependencies,
        outdated_coordinates=sorted({d.coordinate for d in result.dependencies if d.outdated}))


def _kpis(scenario: ClientScenario, cfg: EngineConfig, packages: list[tuple]) -> list[KpiReconciliation]:  # type: ignore[type-arg]
    """Whole-ERP money KPIs restated for the analysed scope, next to the model's own baseline for that scope."""
    share = scenario.analysed_scope_share
    model = {"maintenance_cost": sum(model_maintenance(p[3], cfg) for p in packages) / 1e6,
             "run_cost": sum(p[1].kloc * cfg.tco.run_cost_jpy_per_kloc_year for p in packages) / 1e6}
    out: list[KpiReconciliation] = []
    for o in scenario.objectives:
        adjusted = o.current * share if o.scope == "whole_erp" else o.current
        base = model.get(o.id) if o.scope == "whole_erp" else None
        gap = None if base is None else round(base - adjusted, 4)
        gap_pct = None if gap is None or adjusted == 0 else round(100.0 * gap / adjusted, 2)
        out.append(KpiReconciliation(
            objective=o.id, unit=o.unit, scope=o.scope, kpi_current=o.current, analysed_scope_share=share if o.scope == "whole_erp" else 1.0,
            kpi_current_in_analysed_scope=round(adjusted, 4), model_baseline=None if base is None else round(base, 4),
            gap=gap, gap_pct=gap_pct, flagged=gap_pct is not None and abs(gap_pct) > cfg.calibration.gap_flag_pct))
    return out
