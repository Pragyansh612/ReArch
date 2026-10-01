"""Package dependencies for strangler sequencing: leaves first, entangled packages handled together."""

from __future__ import annotations

from analyzer.graph import strongly_connected
from analyzer.schema import AnalysisResult
from engine.schema import Recommendation


def package_edges(rec: Recommendation, analysis: AnalysisResult) -> dict[str, set[str]]:
    """package -> packages it references (class-level edges lifted to packages)."""
    owner = {c: w.id for w in rec.work_packages.values() for c in w.classes}
    edges: dict[str, set[str]] = {w: set() for w in rec.work_packages}
    for w in rec.work_packages.values():
        for c in w.classes:
            edges[w.id] |= {owner[d] for d in analysis.classes[c].depends_on if d in owner and owner[d] != w.id}
    return edges


def item_dependencies(edges: dict[str, set[str]], items: set[str]) -> dict[str, set[str]]:
    """For each item, the OTHER items it depends on, following paths through packages that are not changing (retained)."""
    out: dict[str, set[str]] = {}
    for a in sorted(items):
        found: set[str] = set()
        seen = {a}
        stack = sorted(edges.get(a, ()))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in items:
                found.add(n)  # stop here: an item is a barrier
            else:
                stack.extend(sorted(edges.get(n, ())))
        out[a] = found - {a}
    return out


def entangled_groups(deps: dict[str, set[str]]) -> list[list[str]]:
    """Strongly connected groups of items (mutual dependencies); every item is in exactly one group."""
    multi = strongly_connected(sorted(deps), deps)
    in_multi = {i for g in multi for i in g}
    return sorted(multi + [[i] for i in sorted(deps) if i not in in_multi], key=lambda g: g[0])
