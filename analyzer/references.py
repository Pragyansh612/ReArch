"""Link non-Java entry points (services.xml, controller.xml) to analysed classes; detect broken references."""

from __future__ import annotations

from collections import Counter

from analyzer import graph as g
from analyzer.config import AnalysisConfig
from analyzer.schema import ControllerMapping, ServiceMapping


def link(mappings: list[ServiceMapping] | list[ControllerMapping], classes: dict[str, g.ClassInfo],
         cfg: AnalysisConfig) -> Counter[str]:
    """Sets class_found / method_found / reference_status on each Java mapping; returns references per class.

    A reference counts toward its class even when the method is missing (the definition still points there).
    `class_missing` is only claimed when the class's module is one we analysed; a class in an unanalysed
    module is `out_of_scope`, not broken.
    """
    index = g.TypeIndex(classes)
    analysed_modules = {c.module for c in classes.values()}
    refs: Counter[str] = Counter()
    for m in mappings:
        if isinstance(m, ServiceMapping) and not m.analyzed:
            continue
        fqn, _, method = m.implementation.partition("#")
        owner = index.owner.get(fqn)
        m.class_found = owner is not None
        m.method_found = owner is not None and (not method or method in classes[owner].parsed.method_names)
        if owner is None:
            module = g.module_of(fqn.rpartition(".")[0], cfg.module_roots)
            m.reference_status = "class_missing" if module in analysed_modules else "out_of_scope"
        else:
            refs[owner] += 1
            m.reference_status = "ok" if m.method_found else "method_missing"
    return refs
