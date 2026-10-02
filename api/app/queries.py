"""Listing, filtering, sorting and the React Flow graph, all read-only over an analysis."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from analyzer.graph import strongly_connected
from analyzer.schema import (
    AnalysisResult,
    ClassMetrics,
    DbInstance,
    Finding,
    LegacyMarker,
    ServiceMapping,
)
from api.app.errors import ApiError, not_found
from api.app.prepared import Prepared, band
from engine.schema import ModuleHealth


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class ModuleRow(BaseModel):
    name: str
    loc: int
    class_count: int
    health: float
    health_band: str
    top_drivers: list[str]
    confidence: str
    java_share: float | None
    has_tests: bool
    namespace_mix: bool
    module_fan_in: int
    module_fan_out: int
    depends_on_modules: dict[str, int]
    package_ids: list[str]


class ModulesPage(Page):
    items: list[ModuleRow]


class PackageRow(BaseModel):
    id: str
    module: str
    kind: str
    name: str
    class_count: int
    loc: int
    health: float
    health_band: str
    top_drivers: list[str]
    confidence: str
    cycle_modules: list[str]


class PackagesPage(Page):
    items: list[PackageRow]


class ClassRow(BaseModel):
    fqn: str
    name: str
    module: str
    package_id: str
    file: str
    loc: int
    complexity: int
    complexity_band: str
    size_tier: str
    fan_in: int
    fan_out: int
    service_fan_in: int
    controller_fan_in: int
    used: bool
    hotspot_score: float


class ClassesPage(Page):
    items: list[ClassRow]


class Edge(BaseModel):
    fqn: str
    name: str
    module: str


class ClassDetail(BaseModel):
    metrics: ClassMetrics
    package_id: str
    hotspot_score: float
    findings: list[Finding]
    db_coupling: list[DbInstance]
    legacy_markers: list[LegacyMarker]
    services: list[ServiceMapping]
    controllers: list[dict[str, Any]]
    depends_on: list[Edge]
    depended_on_by: list[Edge]
    number_id_prefix: str


class Position(BaseModel):
    x: float
    y: float


class GraphNode(BaseModel):
    id: str
    type: Literal["module", "package", "class"]
    position: Position
    data: dict[str, Any]


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    data: dict[str, Any]


class GraphResponse(BaseModel):
    level: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_nodes: int
    truncated: bool
    bands: dict[str, str]


def _page(items: list[Any], sort_key: Any, reverse: bool, limit: int, offset: int) -> tuple[list[Any], int]:
    ordered = sorted(items, key=sort_key, reverse=reverse)
    return ordered[offset: offset + limit], len(ordered)


def _driver_keys(h: ModuleHealth) -> list[str]:
    return h.top_drivers


def modules_page(result: AnalysisResult, prep: Prepared, *, min_loc: int, confidence: str | None, has_tests: bool | None, sort_by: str,
                 descending: bool, limit: int, offset: int) -> ModulesPage:
    rows = []
    for name, m in result.modules.items():
        h = prep.module_health[name]
        rows.append(ModuleRow(
            name=name, loc=m.loc, class_count=m.class_count, health=h.score, health_band=band(h.score), top_drivers=_driver_keys(h),
            confidence=m.coverage.confidence, java_share=m.coverage.java_share, has_tests=m.has_tests, namespace_mix=m.namespace_mix,
            module_fan_in=m.module_fan_in, module_fan_out=m.module_fan_out, depends_on_modules=m.depends_on_modules,
            package_ids=sorted(p for p, f in prep.packages.items() if f.wp.module == name)))
    rows = [r for r in rows if r.loc >= min_loc and (confidence is None or r.confidence == confidence)
            and (has_tests is None or r.has_tests == has_tests)]
    keys = {"name": lambda r: r.name, "loc": lambda r: r.loc, "health": lambda r: r.health, "class_count": lambda r: r.class_count}
    if sort_by not in keys:
        raise ApiError(422, "validation_error", f"sort_by must be one of {sorted(keys)}")
    items, total = _page(rows, keys[sort_by], descending, limit, offset)
    return ModulesPage(total=total, limit=limit, offset=offset, items=items)


def packages_page(prep: Prepared, *, module: str | None, kind: str | None, sort_by: str, descending: bool, limit: int,
                  offset: int) -> PackagesPage:
    rows = [PackageRow(id=pid, module=f.wp.module, kind=f.wp.kind, name=f.wp.name, class_count=len(f.wp.classes), loc=f.loc,
                       health=f.health.score, health_band=band(f.health.score), top_drivers=_driver_keys(f.health),
                       confidence=f.confidence, cycle_modules=f.wp.cycle_modules) for pid, f in prep.packages.items()]
    rows = [r for r in rows if (module is None or r.module == module) and (kind is None or r.kind == kind)]
    keys = {"id": lambda r: r.id, "loc": lambda r: r.loc, "health": lambda r: r.health, "class_count": lambda r: r.class_count}
    if sort_by not in keys:
        raise ApiError(422, "validation_error", f"sort_by must be one of {sorted(keys)}")
    items, total = _page(rows, keys[sort_by], descending, limit, offset)
    return PackagesPage(total=total, limit=limit, offset=offset, items=items)


def _class_row(c: ClassMetrics, prep: Prepared) -> ClassRow:
    return ClassRow(fqn=c.fqn, name=c.name, module=c.module, package_id=prep.class_package.get(c.fqn, ""), file=c.file, loc=c.loc,
                    complexity=c.complexity, complexity_band=c.complexity_band, size_tier=c.size_tier, fan_in=c.fan_in, fan_out=c.fan_out,
                    service_fan_in=c.service_fan_in, controller_fan_in=c.controller_fan_in, used=c.used,
                    hotspot_score=prep.class_hotspot.get(c.fqn, 0.0))


def classes_page(result: AnalysisResult, prep: Prepared, *, q: str | None, module: str | None, package: str | None, tier: str | None,
                 used: bool | None, min_loc: int, sort_by: str, descending: bool, limit: int, offset: int) -> ClassesPage:
    rows = [_class_row(c, prep) for c in result.classes.values()]
    rows = [r for r in rows if (q is None or q.lower() in r.fqn.lower()) and (module is None or r.module == module)
            and (package is None or r.package_id == package) and (tier is None or r.size_tier == tier)
            and (used is None or r.used == used) and r.loc >= min_loc]
    keys = {"loc": lambda r: r.loc, "complexity": lambda r: r.complexity, "fan_in": lambda r: r.fan_in, "fan_out": lambda r: r.fan_out,
            "hotspot": lambda r: r.hotspot_score, "name": lambda r: r.fqn}
    if sort_by not in keys:
        raise ApiError(422, "validation_error", f"sort_by must be one of {sorted(keys)}")
    items, total = _page(rows, keys[sort_by], descending, limit, offset)
    return ClassesPage(total=total, limit=limit, offset=offset, items=items)


def resolve_class(result: AnalysisResult, name: str) -> ClassMetrics:
    if name in result.classes:
        return result.classes[name]
    hits = [c for c in result.classes.values() if c.name == name]
    if not hits:
        raise not_found(f"class '{name}'")
    if len(hits) > 1:
        raise ApiError(409, "ambiguous_class", f"'{name}' matches several classes; use the fully qualified name",
                       [c.fqn for c in sorted(hits, key=lambda c: c.fqn)])
    return hits[0]


def class_detail(result: AnalysisResult, prep: Prepared, analysis_id: str, name: str) -> ClassDetail:
    c = resolve_class(result, name)

    def edge(fqn: str) -> Edge:
        o = result.classes[fqn]
        return Edge(fqn=fqn, name=o.name, module=o.module)

    return ClassDetail(
        metrics=c, package_id=prep.class_package.get(c.fqn, ""), hotspot_score=prep.class_hotspot.get(c.fqn, 0.0),
        findings=[f for f in result.findings if f.subject == c.fqn or (f.file == c.file and f.kind != "outdated_dependency")],
        db_coupling=[d for d in result.db_coupling.instances if d.file == c.file],
        legacy_markers=[m for m in result.legacy_markers if m.file == c.file],
        services=[m for m in result.service_mappings if m.implementation.startswith(c.fqn + "#")],
        controllers=[m.model_dump() for m in result.controller_mappings if m.implementation.startswith(c.fqn + "#")],
        depends_on=[edge(f) for f in c.depends_on], depended_on_by=[edge(f) for f in c.depended_on_by],
        number_id_prefix=f"{analysis_id}:analysis:/classes/{c.fqn.replace('~', '~0').replace('/', '~1')}/")


def _layers(nodes: list[str], deps: dict[str, set[str]]) -> dict[str, int]:
    """Leaves (nothing outgoing) at layer 0; entangled nodes share a layer."""
    comp = {n: n for n in nodes}
    for group in strongly_connected(nodes, deps):
        for n in group:
            comp[n] = group[0]
    cdeps: dict[str, set[str]] = {c: set() for c in set(comp.values())}
    for n in nodes:
        cdeps[comp[n]] |= {comp[d] for d in deps.get(n, ()) if comp[d] != comp[n]}
    depth: dict[str, int] = {}

    def level(c: str) -> int:
        if c not in depth:
            depth[c] = 1 + max((level(d) for d in cdeps[c]), default=-1)
        return depth[c]

    return {n: level(comp[n]) for n in nodes}


def _layout(ids: list[str], deps: dict[str, set[str]], weight: dict[str, float]) -> dict[str, Position]:
    layer = _layers(ids, deps)
    rows: dict[int, int] = {}
    pos: dict[str, Position] = {}
    for n in sorted(ids, key=lambda i: (layer[i], -weight.get(i, 0), i)):
        row = rows.get(layer[n], 0)
        rows[layer[n]] = row + 1
        pos[n] = Position(x=layer[n] * 280.0, y=row * 96.0)
    return pos


def graph(result: AnalysisResult, prep: Prepared, level: str, limit: int, module: str | None, package: str | None) -> GraphResponse:
    nodes_data: dict[str, dict[str, Any]] = {}
    deps: dict[str, set[str]] = {}
    weight: dict[str, float] = {}
    edge_weight: dict[tuple[str, str], int] = {}
    if level == "module":
        for name, m in result.modules.items():
            h = prep.module_health[name]
            nodes_data[name] = {"label": name, "loc": m.loc, "classes": m.class_count, "health": h.score, "band": band(h.score)}
            deps[name] = set(m.depends_on_modules)
            weight[name] = m.loc
            edge_weight.update({(name, d): n for d, n in m.depends_on_modules.items()})
    elif level == "package":
        owner = prep.class_package
        for pid, f in prep.packages.items():
            if module and f.wp.module != module:
                continue
            nodes_data[pid] = {"label": f.wp.name, "module": f.wp.module, "kind": f.wp.kind, "loc": f.loc, "classes": len(f.wp.classes),
                               "health": f.health.score, "band": band(f.health.score)}
            weight[pid] = f.loc
        for pid in nodes_data:
            for cname in prep.packages[pid].wp.classes:
                for d in result.classes[cname].depends_on:
                    target = owner.get(d, "")
                    if target and target != pid and target in nodes_data:
                        edge_weight[(pid, target)] = edge_weight.get((pid, target), 0) + 1
                        deps.setdefault(pid, set()).add(target)
    elif level == "class":
        for cm in result.classes.values():
            if (module and cm.module != module) or (package and prep.class_package.get(cm.fqn) != package):
                continue
            health = round(100.0 - prep.class_hotspot.get(cm.fqn, 0.0), 2)  # a proxy: classes have no health score of their own
            nodes_data[cm.fqn] = {"label": cm.name, "module": cm.module, "loc": cm.loc, "complexity": cm.complexity, "tier": cm.size_tier,
                                 "health": health, "band": band(health), "used": cm.used}
            weight[cm.fqn] = prep.class_hotspot.get(cm.fqn, 0.0)
    else:
        raise ApiError(422, "validation_error", "level must be module, package or class")
    total = len(nodes_data)
    keep = sorted(nodes_data, key=lambda n: (-weight.get(n, 0), n))[:limit]
    keep_set = set(keep)
    if level == "class":
        for fqn in keep:
            for d in result.classes[fqn].depends_on:
                if d in keep_set:
                    edge_weight[(fqn, d)] = 1
                    deps.setdefault(fqn, set()).add(d)
    deps = {n: {d for d in deps.get(n, set()) if d in keep_set} for n in keep}
    pos = _layout(keep, deps, weight)
    edges = [GraphEdge(id=f"{a}->{b}", source=a, target=b, data={"weight": w}) for (a, b), w in sorted(edge_weight.items())
             if a in keep_set and b in keep_set]
    return GraphResponse(level=level, total_nodes=total, truncated=total > len(keep), bands={"good": ">= 60", "fair": ">= 40", "poor": "< 40"},
                         nodes=[GraphNode(id=n, type=level, position=pos[n], data=nodes_data[n]) for n in keep],  # type: ignore[arg-type]
                         edges=edges)
