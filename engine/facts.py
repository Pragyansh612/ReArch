"""Facts for a unit (a whole module or a work package), derived from the analyzer output. Pure arithmetic."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

from analyzer.schema import AnalysisResult, ClassMetrics
from engine.config import EngineConfig


@dataclass
class ModuleContext:
    """Module-level facts a work package inherits (tests, confidence and build files are mapped per module)."""

    name: str
    confidence: str
    java_share: float | None
    has_tests: bool
    tests_per_kloc: float
    in_module_cycle: bool
    own_dependencies: tuple[int, int] | None  # (outdated, checked) when the module has its own build file


@dataclass
class UnitFacts:
    id: str
    module: str
    kind: str  # module | cycle | god_class_cluster | remainder
    classes: list[str]
    loc: int
    kloc: float
    confidence: str
    java_share: float | None
    has_tests: bool
    test_evidence: float
    # LOC-weighted means of class percentiles, 0..100
    size_pct: float
    complexity_pct: float
    coupling_pct: float
    in_module_cycle: bool
    class_cycle_share: float
    db_calls: int
    db_writes: int
    legacy_imports: int
    jakarta_imports: int
    java_inbound: int  # references from classes OUTSIDE this unit
    service_fan_in: int
    controller_fan_in: int
    own_dependencies: tuple[int, int] | None

    @property
    def inbound_total(self) -> int:
        return self.java_inbound + self.service_fan_in + self.controller_fan_in

    @property
    def is_unused(self) -> bool:
        return self.inbound_total == 0


@dataclass
class EstateFacts:
    inbound_total: int
    writes_total: int
    outdated_dependencies: int
    checked_dependencies: int
    unchecked_dependencies: int


def value_of(c: ClassMetrics, key: str) -> float:
    if key == "coupling":
        return (c.fan_in_percentile + c.fan_out_percentile) / 2
    return float(getattr(c, key))


def _weighted(classes: list[ClassMetrics], key: str) -> float:
    total = sum(c.loc for c in classes)
    return sum(c.loc * value_of(c, key) for c in classes) / total if total else 0.0


def _is_write(match: str, typ: str, cfg: EngineConfig) -> bool:
    rule = cfg.criticality
    return match in rule.write_matches or (typ == "jdbc" and rule.jdbc_counts_as_write)


def unit_facts(result: AnalysisResult, cfg: EngineConfig, unit_id: str, kind: str, fqns: list[str],
               ctx: ModuleContext) -> UnitFacts:
    members = set(fqns)
    classes = [result.classes[f] for f in fqns]
    files = {c.file for c in classes}
    in_cycle = {f for group in result.cycles.class_cycles for f in group}
    db = [d for d in result.db_coupling.instances if d.file in files]
    loc = sum(c.loc for c in classes)
    legacy = sum(1 for m in result.legacy_markers if m.file in files and m.namespace != "jakarta")
    jakarta = sum(1 for m in result.legacy_markers if m.file in files and m.namespace == "jakarta")
    kloc = loc / 1000.0
    return UnitFacts(
        id=unit_id, module=ctx.name, kind=kind, classes=list(fqns), loc=loc, kloc=kloc,
        confidence=ctx.confidence, java_share=ctx.java_share, has_tests=ctx.has_tests,
        test_evidence=ctx.tests_per_kloc * kloc, size_pct=_weighted(classes, "loc_percentile"),
        complexity_pct=_weighted(classes, "complexity_percentile"), coupling_pct=_weighted(classes, "coupling"),
        in_module_cycle=ctx.in_module_cycle,
        class_cycle_share=sum(1 for f in fqns if f in in_cycle) / max(1, len(fqns)),
        db_calls=len(db), db_writes=sum(_is_write(d.match, d.type, cfg) for d in db),
        legacy_imports=legacy, jakarta_imports=jakarta,
        java_inbound=sum(1 for c in classes for dep in c.depended_on_by if dep not in members),
        service_fan_in=sum(c.service_fan_in for c in classes),
        controller_fan_in=sum(c.controller_fan_in for c in classes), own_dependencies=ctx.own_dependencies)


def _own_dependencies(result: AnalysisResult, component: str) -> tuple[int, int] | None:
    """Dependencies declared in a build file that sits inside this module's component (not the repo root)."""
    own = [d for d in result.dependencies
           if posixpath.dirname(d.file) and (component + "/").startswith(posixpath.dirname(d.file) + "/")]
    if not own:
        return None
    checked = [d for d in own if d.checked]
    return sum(bool(d.outdated) for d in checked), len(checked)


def build_contexts(result: AnalysisResult) -> dict[str, ModuleContext]:
    in_module_cycle = {m for group in result.cycles.module_cycles for m in group}
    out: dict[str, ModuleContext] = {}
    for name, mod in result.modules.items():
        evidence = mod.test_method_count + max(mod.groovy_test_files, mod.testdef_test_cases)
        kloc = mod.loc / 1000.0
        out[name] = ModuleContext(
            name=name, confidence=mod.coverage.confidence, java_share=mod.coverage.java_share,
            has_tests=mod.has_tests, tests_per_kloc=evidence / kloc if kloc else 0.0,
            in_module_cycle=name in in_module_cycle,
            own_dependencies=_own_dependencies(result, mod.coverage.component))
    return out


def build_module_facts(result: AnalysisResult, cfg: EngineConfig,
                       contexts: dict[str, ModuleContext]) -> tuple[dict[str, UnitFacts], EstateFacts]:
    out = {name: unit_facts(result, cfg, name, "module", list(mod.classes), contexts[name])
           for name, mod in result.modules.items()}
    checked = [d for d in result.dependencies if d.checked]
    estate = EstateFacts(
        inbound_total=sum(f.inbound_total for f in out.values()), writes_total=sum(f.db_writes for f in out.values()),
        outdated_dependencies=sum(bool(d.outdated) for d in checked), checked_dependencies=len(checked),
        unchecked_dependencies=len(result.dependencies) - len(checked))
    return out, estate
