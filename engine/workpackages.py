"""Work packages: the units that receive a strategy, so one module can mix strategies.

(a) every class cycle (strongly connected component) -> one package per module it touches
(b) every extreme god class not already in a cycle, grown with its satellites
(c) the remainder of each module
Each class belongs to exactly one package, so package totals add up to the module totals.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from analyzer.schema import AnalysisResult
from engine.config import EngineConfig


@dataclass
class WorkPackage:
    id: str
    module: str
    kind: str  # cycle | god_class_cluster | remainder
    name: str
    classes: list[str]
    cycle_modules: list[str] = field(default_factory=list)  # modules the whole cycle spans (kind == cycle)


def _short(fqn: str) -> str:
    return fqn.rsplit(".", 1)[-1]


def _dominant(result: AnalysisResult, fqns: list[str], n: int = 2) -> list[str]:
    ranked = sorted(fqns, key=lambda f: (-result.classes[f].loc, f))
    return [_short(f) for f in ranked[:n]]


def _name(result: AnalysisResult, kind: str, module: str, fqns: list[str]) -> str:
    top = _dominant(result, fqns)
    more = f" (+{len(fqns) - len(top)} more)" if len(fqns) > len(top) else ""
    if kind == "cycle":
        return f"{' + '.join(top)}{more}: dependency cycle"
    if kind == "god_class_cluster":
        return f"{top[0]}{' + ' + str(len(fqns) - 1) + ' satellites' if len(fqns) > 1 else ''}: god class"
    return f"{module}: remaining {len(fqns)} classes"


def _neighbours(result: AnalysisResult, module: str) -> dict[str, set[str]]:
    """Undirected in-module adjacency (a reference in either direction links two classes)."""
    members = set(result.modules[module].classes)
    adj: dict[str, set[str]] = {f: set() for f in members}
    for f in members:
        c = result.classes[f]
        adj[f] |= {d for d in c.depends_on if d in members and d != f}
        adj[f] |= {d for d in c.depended_on_by if d in members and d != f}
    return adj


def _grow(seed: str, adj: dict[str, set[str]], free: set[str], extreme: set[str], min_share: float) -> list[str]:
    cluster = {seed}
    changed = True
    while changed:
        changed = False
        for cand in sorted(free - cluster - extreme):
            nbrs = adj[cand]
            if nbrs and len(nbrs & cluster) / len(nbrs) >= min_share:
                cluster.add(cand)
                changed = True
    return sorted(cluster)


def build_work_packages(result: AnalysisResult, cfg: EngineConfig) -> list[WorkPackage]:
    assigned: set[str] = set()
    out: list[WorkPackage] = []
    counters: Counter[str] = Counter()

    def add(module: str, kind: str, fqns: list[str], cycle_modules: list[str] | None = None) -> None:
        counters[f"{module}/{kind}"] += 1
        out.append(WorkPackage(id=f"{module}/{kind.replace('_', '-')}-{counters[f'{module}/{kind}']}", module=module,
                               kind=kind, name=_name(result, kind, module, fqns), classes=sorted(fqns),
                               cycle_modules=cycle_modules or []))
        assigned.update(fqns)

    for cycle in sorted(result.cycles.class_cycles, key=lambda c: (-len(c), c)):
        span = sorted({result.classes[f].module for f in cycle})
        for module in span:
            add(module, "cycle", [f for f in cycle if result.classes[f].module == module], span)
    for module in result.modules:
        members = result.modules[module].classes
        extreme = {f for f in members if result.classes[f].size_tier == "extreme"}
        adj = _neighbours(result, module)
        for seed in sorted(extreme - assigned, key=lambda f: (-result.classes[f].loc, f)):
            free = set(members) - assigned
            add(module, "god_class_cluster", _grow(seed, adj, free, extreme, cfg.work_packages.satellite_min_share))
        rest = [f for f in members if f not in assigned]
        if rest:
            add(module, "remainder", rest)
    return sorted(out, key=lambda w: (w.module, w.kind != "cycle", w.kind != "god_class_cluster", w.id))
