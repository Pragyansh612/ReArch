"""Orchestrates one analysis run: discover -> parse -> metrics -> AnalysisResult."""

from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path

from analyzer import deps as deps_mod
from analyzer import graph as g
from analyzer.config import DEFAULT_CONFIG, AnalysisConfig, CallPattern, load_config
from analyzer.findings import build_findings
from analyzer.java_parser import ParsedJava, parse_java
from analyzer.schema import (
    AnalysisResult,
    ClassMetrics,
    Cycles,
    DbInstance,
    DbSummary,
    Dependency,
    LegacyMarker,
    ModuleMetrics,
    RunMeta,
    ServiceMapping,
    Totals,
    Unanalyzed,
)
from analyzer.services import parse_services
from analyzer.sources import discover, find_dependency_files

ANALYZER_ID = "rearch-analyzer 0.1.0"


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _band(value: int, cfg: AnalysisConfig) -> str:
    bands = cfg.complexity_bands
    return "low" if value <= bands.low_max else "medium" if value <= bands.medium_max else "high"


def _load_classes(paths: list[Path], root: Path, cfg: AnalysisConfig,
                  errors: list[str]) -> dict[str, g.ClassInfo]:
    classes: dict[str, g.ClassInfo] = {}
    for path in paths:
        parsed = parse_java(path.read_bytes())
        if parsed.has_error:
            errors.append(f"{_rel(path, root)}: syntax errors; metrics may be incomplete")
        if not parsed.top_level_types:  # package-info.java, module-info.java
            continue
        name = path.stem if path.stem in parsed.top_level_types else parsed.top_level_types[0]
        fqn = f"{parsed.package}.{name}" if parsed.package else name
        classes[fqn] = g.ClassInfo(fqn, name, g.module_of(parsed.package, cfg.module_roots),
                                   _rel(path, root), parsed.package, parsed.type_lines[name], parsed)
    return classes


def _matches(pattern: CallPattern, receiver: str | None, method: str) -> bool:
    return pattern.method == method and (pattern.receiver is None or pattern.receiver == receiver)


def _db_instances(classes: dict[str, g.ClassInfo], cfg: AnalysisConfig) -> list[DbInstance]:
    rules = (("jdbc", cfg.db_coupling.jdbc), ("entity_engine", cfg.db_coupling.entity_engine))
    out: list[DbInstance] = []
    for info in classes.values():
        if info.name in cfg.db_coupling.ignore_classes:
            continue
        for call in info.parsed.calls:
            for db_type, patterns in rules:
                hit = next((p for p in patterns if _matches(p, call.receiver, call.method)), None)
                if hit:
                    text = f"{hit.receiver}.{hit.method}(" if hit.receiver else f".{hit.method}("
                    out.append(DbInstance(type=db_type, file=info.file, line=call.line,  # type: ignore[arg-type]
                                          module=info.module, class_name=info.name, match=text))
                    break
    return sorted(out, key=lambda d: (d.file, d.line, d.match))


def _markers(classes: dict[str, g.ClassInfo], cfg: AnalysisConfig) -> list[LegacyMarker]:
    out: list[LegacyMarker] = []
    for info in classes.values():
        for imp in info.parsed.imports:
            family, namespace = "", ""
            for fam in cfg.legacy_markers.javax_migrating:
                if imp.name.startswith(f"javax.{fam}."):
                    namespace, family = "javax", fam
            if imp.name.startswith("jakarta."):
                namespace, family = "jakarta", imp.name.split(".")[1]
            for fw, prefixes in cfg.legacy_markers.legacy_frameworks.items():
                if any(imp.name == p or imp.name.startswith(p + ".") for p in prefixes):
                    namespace, family = "legacy_framework", fw
            if namespace:
                out.append(LegacyMarker(file=info.file, line=imp.line, module=info.module, namespace=namespace,
                                        family=family, import_=imp.name + (".*" if imp.wildcard else "")))
    return sorted(out, key=lambda m: (m.file, m.line))


def _services(files: list[Path], root: Path) -> tuple[list[ServiceMapping], list[str]]:
    mappings: list[ServiceMapping] = []
    service_files: list[str] = []
    for path in files:
        parsed = parse_services(path, _rel(path, root))
        if parsed is not None:
            service_files.append(_rel(path, root))
            mappings.extend(parsed)
    return mappings, service_files


def _link_services(mappings: list[ServiceMapping], classes: dict[str, g.ClassInfo]) -> Counter[str]:
    index = g.TypeIndex(classes)
    fan: Counter[str] = Counter()
    for m in mappings:
        if not m.analyzed:
            continue
        fqn, method = m.implementation.split("#", 1)
        owner = index.owner.get(fqn)
        m.class_found = owner is not None
        m.method_found = owner is not None and method in classes[owner].parsed.method_names
        if owner:
            fan[owner] += 1
    return fan


def _tests(paths: list[Path], cfg: AnalysisConfig) -> dict[str, tuple[list[str], int]]:
    per_module: dict[str, tuple[list[str], int]] = {}
    for path in paths:
        parsed: ParsedJava = parse_java(path.read_bytes())
        module = g.module_of(parsed.package, cfg.module_roots)
        names, count = per_module.get(module, ([], 0))
        per_module[module] = (names + [path.stem], count + parsed.test_methods)
    return per_module


def _groovy_tests(paths: list[Path], root: Path, cfg: AnalysisConfig) -> Counter[str]:
    """Groovy test scripts per module, from the `package` line only (the script body is not parsed)."""
    per_module: Counter[str] = Counter()
    for path in paths:
        if f"/{cfg.test_groovy_dir.strip('/')}/" not in "/" + _rel(path, root):
            continue
        match = re.search(r"^\s*package\s+([\w.]+)", path.read_text(errors="replace")[:4000], re.MULTILINE)
        if match:
            per_module[g.module_of(match.group(1), cfg.module_roots)] += 1
    return per_module


def _dependencies(root: Path, cfg: AnalysisConfig) -> list[Dependency]:
    poms, tomls = find_dependency_files(root, cfg)
    out: list[Dependency] = []
    for pom in poms:
        out += deps_mod.evaluate(_rel(pom, root), deps_mod.parse_pom(pom), cfg.dependency_table)
    for toml in tomls:
        out += deps_mod.evaluate(_rel(toml, root), deps_mod.parse_version_catalog(toml), cfg.dependency_table)
    return out


def _module_metrics(classes: dict[str, g.ClassInfo], metrics: dict[str, ClassMetrics],
                    graph: dict[str, set[str]], markers: list[LegacyMarker],
                    tests: dict[str, tuple[list[str], int]],
                    groovy_tests: Counter[str]) -> dict[str, ModuleMetrics]:
    edges = g.module_edges(classes, graph)
    out: dict[str, ModuleMetrics] = {}
    for name in sorted({c.module for c in classes.values()}):
        members = sorted(f for f, c in classes.items() if c.module == name)
        javax = sum(1 for m in markers if m.module == name and m.namespace == "javax")
        jakarta = sum(1 for m in markers if m.module == name and m.namespace == "jakarta")
        test_names, test_methods = tests.get(name, ([], 0))
        out[name] = ModuleMetrics(
            name=name, classes=members, class_count=len(members), loc=sum(metrics[f].loc for f in members),
            depends_on_modules=dict(sorted(edges.get(name, {}).items())), module_fan_out=len(edges.get(name, {})),
            module_fan_in=sum(1 for other in edges.values() if name in other), has_tests=bool(test_names) or groovy_tests[name] > 0,
            test_classes=sorted(test_names), groovy_test_files=groovy_tests[name], test_method_count=test_methods, javax_imports=javax,
            jakarta_imports=jakarta, namespace_mix=javax > 0 and jakarta > 0)
    return out


def analyze(repo: Path, scope: list[str] | None = None, cfg: AnalysisConfig | None = None,
            name: str | None = None, config_path: Path = DEFAULT_CONFIG) -> AnalysisResult:
    started = time.perf_counter()
    cfg = cfg or load_config(config_path)
    repo, scope = repo.resolve(), scope or []
    errors: list[str] = []
    sources = discover(repo, scope, cfg)
    classes = _load_classes(sources.main_java, repo, cfg, errors)
    graph = g.resolve_dependencies(classes)
    inbound = g.invert(graph)
    mappings, service_files = _services(sources.service_xml_candidates, repo)
    service_fan = _link_services(mappings, classes)

    metrics: dict[str, ClassMetrics] = {}
    for fqn, info in sorted(classes.items()):
        p = info.parsed
        metrics[fqn] = ClassMetrics(
            name=info.name, fqn=fqn, module=info.module, file=info.file, loc=p.loc, fan_in=len(inbound[fqn]),
            fan_out=len(graph[fqn]), service_fan_in=service_fan[fqn], used=len(inbound[fqn]) + service_fan[fqn] > 0,
            complexity=p.complexity, complexity_band=_band(p.complexity, cfg),  # type: ignore[arg-type]
            depends_on=sorted(graph[fqn]), depended_on_by=sorted(inbound[fqn]))

    markers = _markers(classes, cfg)
    tests = _tests(sources.test_java, cfg)
    modules = _module_metrics(classes, metrics, graph, markers, tests,
                              _groovy_tests(sources.groovy, repo, cfg))
    mod_graph = {m: set(v.depends_on_modules) for m, v in modules.items()}
    cycles = Cycles(module_cycles=g.strongly_connected(list(modules), mod_graph),
                    class_cycles=g.strongly_connected(list(classes), graph))
    db = _db_instances(classes, cfg)
    dependencies = _dependencies(repo, cfg)
    groovy = sorted(_rel(p, repo) for p in sources.groovy)
    infos = {f: classes[f] for f in classes}
    return AnalysisResult(
        meta=RunMeta(name=name or repo.name, repo_path=str(repo), scope=scope, analyzer=ANALYZER_ID,
                     runtime_seconds=round(time.perf_counter() - started, 3), config_file=str(config_path),
                     dependency_table_as_of=cfg.dependency_table.as_of, parse_errors=errors),
        totals=Totals(main_java_classes=len(classes), modules=len(modules),
                      main_java_loc=sum(m.loc for m in metrics.values()),
                      test_classes=sum(len(t[0]) for t in tests.values()),
                      dependencies_declared=len(dependencies),
                      dependencies_checked=sum(d.checked for d in dependencies)),
        modules=modules, classes=metrics, cycles=cycles,
        db_coupling=DbSummary(total=len(db), jdbc=sum(d.type == "jdbc" for d in db),
                              entity_engine=sum(d.type == "entity_engine" for d in db), instances=db),
        legacy_markers=markers, dependencies=dependencies, service_mappings=mappings,
        unanalyzed_files=Unanalyzed(groovy_count=len(groovy), groovy_files=groovy, service_xml_files=service_files,
                                    service_engine_counts=dict(sorted(Counter(m.engine for m in mappings).items()))),
        findings=build_findings(metrics, infos, modules, cycles, dependencies, cfg))
