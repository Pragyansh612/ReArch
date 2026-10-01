"""Module-level measures derived from the analyzer output. Pure arithmetic; no scoring decisions here."""

from __future__ import annotations

from dataclasses import dataclass

from analyzer.schema import AnalysisResult, ClassMetrics
from engine.config import EngineConfig


@dataclass
class ModuleFacts:
    name: str
    loc: int
    kloc: float
    class_fqns: list[str]
    confidence: str
    java_share: float | None
    has_tests: bool
    test_evidence: int  # Java @Test methods + Groovy test scripts
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
    java_cross_module_fan_in: int
    service_fan_in: int
    controller_fan_in: int

    @property
    def inbound_total(self) -> int:
        return self.java_cross_module_fan_in + self.service_fan_in + self.controller_fan_in

    @property
    def is_unused(self) -> bool:
        return self.inbound_total == 0


@dataclass
class EstateFacts:
    inbound_total: int
    writes_total: int
    outdated_dependencies: int
    checked_dependencies: int


def _weighted(classes: list[ClassMetrics], value: str) -> float:
    total = sum(c.loc for c in classes)
    return sum(c.loc * float(value_of(c, value)) for c in classes) / total if total else 0.0


def value_of(c: ClassMetrics, key: str) -> float:
    if key == "coupling":
        return (c.fan_in_percentile + c.fan_out_percentile) / 2
    return float(getattr(c, key))


def _is_write(match: str, typ: str, cfg: EngineConfig) -> bool:
    rule = cfg.criticality
    return match in rule.write_matches or (typ == "jdbc" and rule.jdbc_counts_as_write)


def build_facts(result: AnalysisResult, cfg: EngineConfig) -> tuple[dict[str, ModuleFacts], EstateFacts]:
    in_cycle_classes = {f for group in result.cycles.class_cycles for f in group}
    in_cycle_modules = {m for group in result.cycles.module_cycles for m in group}
    out: dict[str, ModuleFacts] = {}
    for name, mod in result.modules.items():
        classes = [result.classes[f] for f in mod.classes]
        db = [d for d in result.db_coupling.instances if d.module == name]
        cross = sum(1 for c in classes for dep in c.depended_on_by if result.classes[dep].module != name)
        legacy = sum(1 for m in result.legacy_markers if m.module == name and m.namespace != "jakarta")
        out[name] = ModuleFacts(
            name=name, loc=mod.loc, kloc=mod.loc / 1000.0, class_fqns=list(mod.classes),
            confidence=mod.coverage.confidence, java_share=mod.coverage.java_share, has_tests=mod.has_tests,
            test_evidence=mod.test_method_count + mod.groovy_test_files,
            size_pct=_weighted(classes, "loc_percentile"), complexity_pct=_weighted(classes, "complexity_percentile"),
            coupling_pct=_weighted(classes, "coupling"), in_module_cycle=name in in_cycle_modules,
            class_cycle_share=sum(1 for f in mod.classes if f in in_cycle_classes) / max(1, len(mod.classes)),
            db_calls=len(db), db_writes=sum(_is_write(d.match, d.type, cfg) for d in db),
            legacy_imports=legacy, jakarta_imports=sum(1 for m in result.legacy_markers
                                                       if m.module == name and m.namespace == "jakarta"),
            java_cross_module_fan_in=cross, service_fan_in=sum(c.service_fan_in for c in classes),
            controller_fan_in=sum(c.controller_fan_in for c in classes))
    checked = [d for d in result.dependencies if d.checked]
    estate = EstateFacts(inbound_total=sum(f.inbound_total for f in out.values()),
                         writes_total=sum(f.db_writes for f in out.values()),
                         outdated_dependencies=sum(bool(d.outdated) for d in checked),
                         checked_dependencies=len(checked))
    return out, estate
