"""Turn metrics into Findings: concrete issues with evidence (file, line, metric value)."""

from __future__ import annotations

from analyzer.config import AnalysisConfig
from analyzer.graph import ClassInfo
from analyzer.schema import (
    ClassMetrics,
    ControllerMapping,
    Cycles,
    Dependency,
    Finding,
    ModuleMetrics,
    ServiceMapping,
)


def is_god_class(m: ClassMetrics, cfg: AnalysisConfig) -> bool:
    return m.size_tier != "none"


def is_highly_coupled(m: ClassMetrics, cfg: AnalysisConfig) -> bool:
    rule = cfg.highly_coupled
    return m.fan_in >= rule.min_fan_in and m.fan_out >= rule.min_fan_out


def build_findings(
    classes: dict[str, ClassMetrics], infos: dict[str, ClassInfo], modules: dict[str, ModuleMetrics],
    cycles: Cycles, dependencies: list[Dependency], services: list[ServiceMapping],
    controllers: list[ControllerMapping], cfg: AnalysisConfig,
) -> list[Finding]:
    out: list[Finding] = []
    for fqn, m in sorted(classes.items()):
        line = infos[fqn].decl_line
        if is_god_class(m, cfg):
            out.append(Finding(kind="god_class", subject=fqn, file=m.file, line=line, metric="complexity",
                               value=m.complexity, tier=m.size_tier,
                               detail=f"{m.size_tier}: loc={m.loc}, complexity={m.complexity}"))
        if is_highly_coupled(m, cfg):
            out.append(Finding(kind="highly_coupled", subject=fqn, file=m.file, line=line, metric="fan_out",
                               value=m.fan_out, detail=f"fan_in={m.fan_in}, fan_out={m.fan_out}"))
    for name, mod in sorted(modules.items()):
        if not mod.has_tests:
            out.append(Finding(kind="module_without_tests", subject=name, metric="loc", value=mod.loc,
                               detail=f"{mod.class_count} classes, {mod.loc} LOC, no Java or Groovy tests"))
        if mod.namespace_mix:
            out.append(Finding(kind="namespace_mix", subject=name, metric="javax_imports",
                               value=mod.javax_imports,
                               detail=f"{mod.javax_imports} javax and {mod.jakarta_imports} jakarta imports"))
    for group in cycles.module_cycles:
        out.append(Finding(kind="module_cycle", subject=" <-> ".join(group), metric="modules",
                           value=len(group), detail="modules depend on each other in a cycle"))
    for dep in dependencies:
        if dep.outdated:
            out.append(Finding(kind="outdated_dependency", subject=dep.coordinate, file=dep.file,
                               metric="declared_major", value=dep.declared_major or 0,
                               detail=_outdated_detail(dep)))
    out += _broken_references(services, controllers)
    return out


def _outdated_detail(dep: Dependency) -> str:
    if dep.superseded_by:
        return f"{dep.declared_version} is declared under a superseded name; successor: {dep.superseded_by}"
    return f"{dep.declared_version} (major {dep.declared_major}); latest stable {dep.latest_stable_version}"


def _broken_references(services: list[ServiceMapping], controllers: list[ControllerMapping]) -> list[Finding]:
    out: list[Finding] = []
    reasons = {"method_missing": "class exists but has no such method", "class_missing": "class not found in analysed module"}
    for kind, items in (("service", services), ("controller request", controllers)):
        for m in items:
            if m.reference_status in reasons:
                name = m.service if isinstance(m, ServiceMapping) else m.request
                out.append(Finding(kind="broken_reference", subject=f"{kind} {name}", file=m.file, line=m.line,
                                   metric="reference_status", value=m.reference_status,
                                   detail=f"{m.implementation}: {reasons[m.reference_status]}"))
    return out
