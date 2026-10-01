"""Class and module dependency graph: reference resolution, fan-in/out, cycles."""

from __future__ import annotations

from dataclasses import dataclass

from analyzer.java_parser import ParsedJava


@dataclass
class ClassInfo:
    fqn: str
    name: str
    module: str
    file: str  # relative to the repo root
    package: str
    decl_line: int
    parsed: ParsedJava


def module_of(package: str, roots: list[str]) -> str:
    """First package segment after the longest matching module root."""
    for root in sorted(roots, key=len, reverse=True):
        if package == root:
            return root.rsplit(".", 1)[-1]
        if package.startswith(root + "."):
            return package[len(root) + 1:].split(".")[0]
    return package or "(default)"


class TypeIndex:
    """Maps every top-level type to the class record (file) that owns it."""

    def __init__(self, classes: dict[str, ClassInfo]) -> None:
        self.owner: dict[str, str] = {}
        self.by_package: dict[str, dict[str, str]] = {}
        for info in classes.values():
            for type_name in info.parsed.top_level_types:
                fqn = f"{info.package}.{type_name}" if info.package else type_name
                self.owner[fqn] = info.fqn
                self.by_package.setdefault(info.package, {})[type_name] = info.fqn

    def resolve(self, dotted: str) -> str | None:
        """Owner of `a.b.Outer` or `a.b.Outer.Inner` (nested types resolve to their outer type)."""
        parts = dotted.split(".")
        while parts:
            hit = self.owner.get(".".join(parts))
            if hit:
                return hit
            parts.pop()
        return None


def _imported(info: ClassInfo, index: TypeIndex) -> tuple[set[str], set[str]]:
    """(dependencies from explicit/static imports, simple names claimed by explicit imports)."""
    deps: set[str] = set()
    claimed: set[str] = set()
    for imp in info.parsed.imports:
        if imp.wildcard and not imp.static:
            continue
        last = imp.name.rsplit(".", 1)[-1]
        if imp.static:
            owner = index.resolve(imp.name if imp.wildcard else imp.name.rsplit(".", 1)[0])
            if owner and (imp.wildcard or last in info.parsed.identifiers):
                deps.add(owner)
            continue
        claimed.add(last)
        owner = index.resolve(imp.name)
        if owner and last in info.parsed.identifiers:
            deps.add(owner)
    return deps, claimed


def resolve_dependencies(classes: dict[str, ClassInfo]) -> dict[str, set[str]]:
    """Class -> distinct OTHER analysed classes referenced in code.

    A name counts when it appears as an identifier in code (comments, strings and import lines do not
    count) and resolves, in Java's order, through an explicit import, the same package, or a wildcard import.
    """
    index = TypeIndex(classes)
    graph: dict[str, set[str]] = {}
    for info in classes.values():
        deps, claimed = _imported(info, index)
        wildcards = [i.name for i in info.parsed.imports if i.wildcard and not i.static]
        for name in info.parsed.identifiers - claimed:
            hit = index.by_package.get(info.package, {}).get(name)
            for pkg in wildcards:
                hit = hit or index.by_package.get(pkg, {}).get(name)
            if hit:
                deps.add(hit)
        deps.discard(info.fqn)
        graph[info.fqn] = deps
    return graph


def invert(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    inbound: dict[str, set[str]] = {n: set() for n in graph}
    for src, targets in graph.items():
        for dst in targets:
            inbound.setdefault(dst, set()).add(src)
    return inbound


def module_edges(classes: dict[str, ClassInfo], graph: dict[str, set[str]]) -> dict[str, dict[str, int]]:
    edges: dict[str, dict[str, int]] = {}
    for src, targets in graph.items():
        for dst in targets:
            a, b = classes[src].module, classes[dst].module
            if a != b:
                edges.setdefault(a, {})[b] = edges.get(a, {}).get(b, 0) + 1
    return edges


def strongly_connected(nodes: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's algorithm (iterative). Returns only components with more than one node."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    found: list[list[str]] = []
    counter = 0
    for start in sorted(nodes):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        work = [(start, iter(sorted(edges.get(start, ()))))]
        while work:
            node, children = work[-1]
            descended = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(edges.get(child, ())))))
                    descended = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    found.append(sorted(component))
    return sorted(found)
