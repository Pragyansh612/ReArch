"""Analysis coverage per module, plus estate percentiles and size tiers."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from pathlib import Path

from analyzer import graph as g
from analyzer.config import AnalysisConfig, CoverageRules, TierRule
from analyzer.schema import Confidence, Coverage, ServiceMapping, SizeTier


def component_of(rel_path: str, markers: list[str]) -> str:
    """Directory that owns a file: the path before the first marker directory (src, servicedef, webapp, ...)."""
    path = "/" + rel_path
    cuts = [path.find(f"/{m}/") for m in markers]
    cut = min((c for c in cuts if c >= 0), default=path.rfind("/"))
    return path[:cut].lstrip("/")


def percentiles(values: dict[str, float]) -> dict[str, float]:
    """Share (0-100) of classes with a STRICTLY lower value: the biggest is near 100, a zero stays 0."""
    ordered = sorted(values.values())
    n = len(ordered)
    return {k: round(100.0 * bisect_left(ordered, v) / n, 4) for k, v in values.items()}


def tier(loc: int, complexity: int, cfg: AnalysisConfig) -> SizeTier:
    def hit(rule: TierRule) -> bool:
        return loc >= rule.min_loc and complexity > rule.min_complexity_above

    return "extreme" if hit(cfg.god_class.extreme) else "large" if hit(cfg.god_class) else "none"


def _confidence(share: float | None, groovy_files: int, rules: CoverageRules) -> Confidence:
    if share is None:  # no service definitions: judge by whether Groovy logic exists at all
        return "high" if groovy_files == 0 else "medium"
    if share >= rules.high_min_java_share:
        return "high"
    return "medium" if share >= rules.medium_min_java_share else "low"


def module_coverage(
    classes: dict[str, g.ClassInfo], mappings: list[ServiceMapping], groovy: list[Path], root: Path,
    cfg: AnalysisConfig,
) -> dict[str, Coverage]:
    rules = cfg.coverage
    by_component: dict[str, Counter[str]] = {}
    for m in mappings:
        by_component.setdefault(component_of(m.file, rules.component_dir_markers), Counter())[m.engine] += 1
    groovy_logic: Counter[str] = Counter()
    for path in groovy:
        rel = path.relative_to(root).as_posix()
        if f"/{cfg.test_groovy_dir.strip('/')}/" not in "/" + rel:
            groovy_logic[component_of(rel, rules.component_dir_markers)] += 1
    out: dict[str, Coverage] = {}
    for module in sorted({c.module for c in classes.values()}):
        homes = Counter(component_of(c.file, rules.component_dir_markers) for c in classes.values()
                        if c.module == module)
        component = min(homes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        engines = by_component.get(component, Counter())
        implemented = sum(n for e, n in engines.items() if e not in rules.non_implementing_engines)
        java = engines.get("java", 0)
        share = round(java / implemented, 4) if implemented else None
        out[module] = Coverage(
            component=component, service_defs_total=sum(engines.values()),
            service_defs_by_engine=dict(sorted(engines.items())), implemented_defs=implemented, java_defs=java,
            java_share=share, groovy_logic_files=groovy_logic[component],
            confidence=_confidence(share, groovy_logic[component], rules))
    return out
