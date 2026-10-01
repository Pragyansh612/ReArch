"""Orchestrates one analysis run: discover -> parse -> metrics -> AnalysisResult."""

from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path

from analyzer import coverage as cov
from analyzer import deps as deps_mod
from analyzer import graph as g
from analyzer import references
from analyzer.config import DEFAULT_CONFIG, AnalysisConfig, CallPattern, load_config
from analyzer.controller import parse_controller
from analyzer.findings import build_findings
from analyzer.java_parser import ParsedJava, parse_java
from analyzer.schema import (
    AnalysisResult,
    ClassMetrics,
    ControllerMapping,
    Coverage,
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
from analyzer.testdef import parse_testdef

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


def _controllers(files: list[Path], root: Path) -> tuple[list[ControllerMapping], list[str], dict[str, int]]:
    mappings: list[ControllerMapping] = []
    controller_files: list[str] = []
    counts: Counter[str] = Counter()
    for path in files:
        parsed = parse_controller(path, _rel(path, root))
        if parsed is not None:
            controller_files.append(_rel(path, root))
            mappings.extend(parsed[0])
            counts.update(parsed[1])
    return mappings, controller_files, dict(sorted(counts.items()))


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


def _testdef(files: list[Path], root: Path, cfg: AnalysisConfig,
             coverage: dict[str, Coverage]) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """Per module: (suite files, test cases). A case is attributed to the module of its `class-name` package;
    cases without one go to every module of the file's component."""
    suites: dict[str, set[str]] = {}
    cases: Counter[str] = Counter()
    listed: list[str] = []
    for path in files:
        parsed = parse_testdef(path, cfg.testdef_data_load_elements)
        if parsed is None:
            continue
        rel = _rel(path, root)
        listed.append(rel)
        component = cov.component_of(rel, cfg.coverage.component_dir_markers)
        for case in parsed:
            owners = ([g.module_of(case.class_name.rpartition(".")[0], cfg.module_roots)] if case.class_name else
                      [m for m, c in coverage.items() if c.component == component])
            for module in owners:
                cases[module] += 1
                suites.setdefault(module, set()).add(rel)
    return {m: (len(suites[m]), cases[m]) for m in suites}, listed


def _dependencies(root: Path, cfg: AnalysisConfig) -> list[Dependency]:
    poms, tomls = find_dependency_files(root, cfg)
    out: list[Dependency] = []
    for pom in poms:
        out += deps_mod.evaluate(_rel(pom, root), deps_mod.parse_pom(pom), cfg.dependency_snapshot,
                                  cfg.date_based_version_min)
    for toml in tomls:
        out += deps_mod.evaluate(_rel(toml, root), deps_mod.parse_version_catalog(toml), cfg.dependency_snapshot,
                                  cfg.date_based_version_min)
    return out


def _module_metrics(classes: dict[str, g.ClassInfo], metrics: dict[str, ClassMetrics],
                    graph: dict[str, set[str]], markers: list[LegacyMarker],
                    tests: dict[str, tuple[list[str], int]], groovy_tests: Counter[str],
                    coverage: dict[str, Coverage], testdef: dict[str, tuple[int, int]]) -> dict[str, ModuleMetrics]:
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
            module_fan_in=sum(1 for other in edges.values() if name in other), has_tests=bool(test_names) or groovy_tests[name] > 0 or testdef.get(name, (0, 0))[1] > 0,
            test_classes=sorted(test_names), groovy_test_files=groovy_tests[name], test_method_count=test_methods,
            testdef_suite_files=testdef.get(name, (0, 0))[0], testdef_test_cases=testdef.get(name, (0, 0))[1], javax_imports=javax,
            jakarta_imports=jakarta, namespace_mix=javax > 0 and jakarta > 0, coverage=coverage[name])
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
    service_fan = references.link(mappings, classes, cfg)
    controllers, controller_files, controller_counts = _controllers(sources.controller_xml, repo)
    controller_fan = references.link(controllers, classes, cfg)

    raw = {"loc": {f: float(c.parsed.loc) for f, c in classes.items()},
           "complexity": {f: float(c.parsed.complexity) for f, c in classes.items()},
           "fan_out": {f: float(len(graph[f])) for f in classes},
           "fan_in": {f: float(len(inbound[f])) for f in classes}}
    pct = {key: cov.percentiles(values) for key, values in raw.items()}
    metrics: dict[str, ClassMetrics] = {}
    for fqn, info in sorted(classes.items()):
        p = info.parsed
        inbound_total = len(inbound[fqn]) + service_fan[fqn] + controller_fan[fqn]
        metrics[fqn] = ClassMetrics(
            name=info.name, fqn=fqn, module=info.module, file=info.file, loc=p.loc, fan_in=len(inbound[fqn]),
            fan_out=len(graph[fqn]), service_fan_in=service_fan[fqn], controller_fan_in=controller_fan[fqn],
            used=inbound_total > 0, complexity=p.complexity, complexity_band=_band(p.complexity, cfg),  # type: ignore[arg-type]
            size_tier=cov.tier(p.loc, p.complexity, cfg), loc_percentile=pct["loc"][fqn],
            complexity_percentile=pct["complexity"][fqn], fan_in_percentile=pct["fan_in"][fqn],
            fan_out_percentile=pct["fan_out"][fqn], depends_on=sorted(graph[fqn]), depended_on_by=sorted(inbound[fqn]))

    markers = _markers(classes, cfg)
    tests = _tests(sources.test_java, cfg)
    coverage = cov.module_coverage(classes, mappings, sources.groovy, repo, cfg)
    testdef, testdef_files = _testdef(sources.testdef_xml, repo, cfg, coverage)
    modules = _module_metrics(classes, metrics, graph, markers, tests,
                              _groovy_tests(sources.groovy, repo, cfg), coverage, testdef)
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
                     dependency_snapshot_as_of=cfg.dependency_snapshot.as_of, parse_errors=errors),
        totals=Totals(main_java_classes=len(classes), modules=len(modules),
                      main_java_loc=sum(m.loc for m in metrics.values()),
                      test_classes=sum(len(t[0]) for t in tests.values()),
                      dependencies_declared=len(dependencies),
                      dependencies_checked=sum(d.checked for d in dependencies)),
        modules=modules, classes=metrics, cycles=cycles,
        db_coupling=DbSummary(total=len(db), jdbc=sum(d.type == "jdbc" for d in db),
                              entity_engine=sum(d.type == "entity_engine" for d in db), instances=db),
        legacy_markers=markers, dependencies=dependencies, service_mappings=mappings, controller_mappings=controllers,
        unanalyzed_files=Unanalyzed(groovy_count=len(groovy), groovy_files=groovy, service_xml_files=service_files,
                                    service_engine_counts=dict(sorted(Counter(m.engine for m in mappings).items())),
                                    controller_xml_files=controller_files, testdef_files=testdef_files, controller_event_counts=controller_counts),
        findings=build_findings(metrics, infos, modules, cycles, dependencies, mappings, controllers, cfg))
