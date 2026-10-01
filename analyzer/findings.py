"""Turn metrics into Findings: concrete issues with evidence (file, line, metric value)."""

from __future__ import annotations

from analyzer.config import AnalysisConfig
from analyzer.graph import ClassInfo
from analyzer.schema import ClassMetrics, Cycles, Dependency, Finding, ModuleMetrics


def is_god_class(m: ClassMetrics, cfg: AnalysisConfig) -> bool:
    rule = cfg.god_class
    return m.loc >= rule.min_loc and m.complexity > rule.min_complexity_above


def is_highly_coupled(m: ClassMetrics, cfg: AnalysisConfig) -> bool:
    rule = cfg.highly_coupled
    return m.fan_in >= rule.min_fan_in and m.fan_out >= rule.min_fan_out


def build_findings(
    classes: dict[str, ClassMetrics], infos: dict[str, ClassInfo], modules: dict[str, ModuleMetrics],
    cycles: Cycles, dependencies: list[Dependency], cfg: AnalysisConfig,
) -> list[Finding]:
    out: list[Finding] = []
    for fqn, m in sorted(classes.items()):
        line = infos[fqn].decl_line
        if is_god_class(m, cfg):
            out.append(Finding(kind="god_class", subject=fqn, file=m.file, line=line, metric="complexity",
                               value=m.complexity, detail=f"loc={m.loc}, complexity={m.complexity}"))
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
                               detail=f"{dep.declared_version} (major {dep.declared_major}) "
                                      f"< current major >= {dep.min_current_major}"))
    return out
