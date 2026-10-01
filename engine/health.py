"""Technical health per module (0-100) and the class-level hotspot list. Fully decomposed."""

from __future__ import annotations

import math

from analyzer.schema import AnalysisResult, ClassMetrics
from engine.config import EngineConfig
from engine.facts import UnitFacts
from engine.schema import HealthComponent, Hotspot, HotspotComponent, ModuleHealth

LABELS = {
    "size": "Size", "complexity": "Complexity", "coupling": "Coupling (fan-in/out)", "cycles": "Dependency cycles",
    "test_evidence": "Test evidence", "db_coupling": "Database coupling", "legacy_markers": "Legacy namespaces",
    "outdated_dependencies": "Outdated dependencies (own build file)",
}


def db_scale(per_kloc: float, cfg: EngineConfig) -> float:
    """Log scale 0..1: ln(1 + calls/KLOC) / ln(1 + reference). Non-saturating below the (high) reference."""
    return min(1.0, math.log1p(per_kloc) / math.log1p(cfg.health.db_calls_per_kloc_reference))


def _weights(f: UnitFacts, cfg: EngineConfig) -> dict[str, float]:
    base = cfg.health.weights
    if f.own_dependencies is None:
        return dict(base)
    own = cfg.health.own_build_file_weight
    return {**{k: v * (1.0 - own) for k, v in base.items()}, "outdated_dependencies": own}


def _component(key: str, raw: float, unit: str, normalized: float, how: str, weight: float) -> HealthComponent:
    normalized = min(1.0, max(0.0, normalized))
    return HealthComponent(key=key, label=LABELS[key], raw=round(raw, 4), raw_unit=unit,
                           normalized=round(normalized, 6), weight=weight,
                           contribution_points=round(100.0 * weight * normalized, 4), how=how)


def unit_health(f: UnitFacts, cfg: EngineConfig) -> ModuleHealth:
    h, w = cfg.health, _weights(f, cfg)
    tests_per_kloc = f.test_evidence / f.kloc if f.kloc else 0.0
    db_per_kloc = f.db_calls / f.kloc if f.kloc else 0.0
    legacy_total = f.legacy_imports + f.jakarta_imports
    legacy_share = f.legacy_imports / legacy_total if legacy_total else 0.0
    cycles_raw = 0.5 * f.in_module_cycle + 0.5 * f.class_cycle_share
    parts = [
        _component("size", f.size_pct, "percentile", f.size_pct / 100,
                   "LOC-weighted mean of each class's LOC percentile within the analysed estate", w["size"]),
        _component("complexity", f.complexity_pct, "percentile", f.complexity_pct / 100,
                   "LOC-weighted mean of each class's complexity percentile", w["complexity"]),
        _component("coupling", f.coupling_pct, "percentile", f.coupling_pct / 100,
                   "LOC-weighted mean of the average of each class's fan-in and fan-out percentiles", w["coupling"]),
        _component("cycles", cycles_raw, "0-1", cycles_raw,
                   "0.5 if the module is in a module-level cycle + 0.5 x share of the unit's classes in class cycles",
                   w["cycles"]),
        _component("test_evidence", tests_per_kloc, "tests per KLOC",
                   1.0 - min(1.0, tests_per_kloc / h.test_target_per_kloc),
                   f"1 - min(1, tests per KLOC / {h.test_target_per_kloc:g}); tests = Java @Test + max(Groovy test "
                   "files, testdef cases); a work package inherits its module's tests per KLOC", w["test_evidence"]),
        _component("db_coupling", db_per_kloc, "db calls per KLOC", db_scale(db_per_kloc, cfg),
                   f"ln(1 + calls per KLOC) / ln(1 + {h.db_calls_per_kloc_reference:g}) (log scale, capped at 1)",
                   w["db_coupling"]),
        _component("legacy_markers", legacy_share, "share of namespace imports", legacy_share,
                   "javax.* and legacy-framework imports / (those + jakarta.* imports)", w["legacy_markers"]),
    ]
    if f.own_dependencies is not None:
        outdated, checked = f.own_dependencies
        share = outdated / checked if checked else 0.0
        parts.append(_component("outdated_dependencies", share, "share of checked dependencies", share,
                                "outdated / checked dependencies in the module's own build file",
                                w["outdated_dependencies"]))
    score = round(100.0 - sum(p.contribution_points for p in parts), 4)
    drivers = [p.key for p in sorted(parts, key=lambda p: (-p.contribution_points, p.key))[:3]]
    return ModuleHealth(score=score, components=parts, top_drivers=drivers)


def _class_flags(c: ClassMetrics, in_cycle: bool, module_has_tests: bool) -> list[str]:
    flags = [f"{c.size_tier}_god_class"] if c.size_tier != "none" else []
    flags += ["in_cycle"] if in_cycle else []
    flags += ["module_without_tests"] if not module_has_tests else []
    flags += ["unused"] if not c.used else []
    return flags


def hotspots(result: AnalysisResult, cfg: EngineConfig) -> list[Hotspot]:
    in_cycle = {f for group in result.cycles.class_cycles for f in group}
    db_by_class: dict[str, int] = {}
    for d in result.db_coupling.instances:
        db_by_class[d.file] = db_by_class.get(d.file, 0) + 1
    out: list[Hotspot] = []
    for fqn, c in result.classes.items():
        per_kloc = db_by_class.get(c.file, 0) / (c.loc / 1000.0) if c.loc else 0.0
        values = {"complexity_percentile": c.complexity_percentile, "loc_percentile": c.loc_percentile,
                  "fan_out_percentile": c.fan_out_percentile, "fan_in_percentile": c.fan_in_percentile,
                  "db_density": 100.0 * db_scale(per_kloc, cfg),
                  "in_cycle": 100.0 if fqn in in_cycle else 0.0}
        parts = [HotspotComponent(key=k, value=round(values[k], 4), weight=w, contribution=round(w * values[k], 4))
                 for k, w in cfg.hotspots.weights.items()]
        out.append(Hotspot(fqn=fqn, module=c.module, file=c.file, loc=c.loc, complexity=c.complexity,
                           size_tier=c.size_tier, score=round(sum(p.contribution for p in parts), 4), components=parts,
                           flags=_class_flags(c, fqn in in_cycle, result.modules[c.module].has_tests)))
    return sorted(out, key=lambda h: (-h.score, h.fqn))[: cfg.hotspots.top_n]
