"""Focused unit tests for parsers and graph helpers."""

from __future__ import annotations

from pathlib import Path

from analyzer.config import DependencySnapshot, SnapshotEntry
from analyzer.deps import evaluate, major, parse_pom, parse_version_catalog
from analyzer.graph import module_of, strongly_connected
from analyzer.java_parser import parse_java


def test_module_of_uses_longest_root() -> None:
    roots = ["org.apache.ofbiz", "com.example.legacy"]
    assert module_of("org.apache.ofbiz.order.order", roots) == "order"
    assert module_of("com.example.legacy.billing", roots) == "billing"
    assert module_of("unknown.pkg", roots) == "unknown.pkg"


def test_scc_finds_only_real_cycles() -> None:
    edges = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}, "e": set()}
    assert strongly_connected(list("abcde"), edges) == [["a", "b", "c"]]


def test_loc_ignores_comments_and_blank_lines() -> None:
    src = b"package p;\n\n// c\n/* a\n b */\nclass A { /* x */ int f; }\n"
    assert parse_java(src).loc == 2


def test_complexity_counts_decisions() -> None:
    src = b"class A { int f(int x){ if (x>1 && x<3) { return x>0 ? 1 : 2; } for(;;){} return 0; } }"
    p = parse_java(src)
    assert (p.bodies, p.decisions) == (1, 4)  # if, &&, ternary, for


def test_else_and_default_do_not_count() -> None:
    src = b"class A { void f(int x){ if (x>1) {} else {} switch(x){ case 1: break; default: break; } } }"
    assert parse_java(src).decisions == 2  # if + case


def test_major_parsing() -> None:
    assert major("4.3.30.RELEASE") == 4
    assert major("${x}") is None
    assert major(None) is None


def test_snapshot_drives_outdated_unchecked_and_superseded() -> None:
    snap = DependencySnapshot(as_of="2026-10-01", source="test", entries={
        "a:b": SnapshotEntry(latest_stable_version="5.1", latest_major=5),
        "old:name": SnapshotEntry(latest_stable_version="1.0", latest_major=1, superseded_by="new:name"),
        "no:latest": SnapshotEntry(latest_stable_version=None, latest_major=None)})
    out = evaluate("f", [("a:b", "1.0"), ("a:b", "5.0"), ("x:y", "1.0"), ("a:b", None), ("old:name", "1.0"),
                         ("no:latest", "1.0")], snap)
    assert [(d.checked, d.outdated) for d in out] == [
        (True, True), (True, False), (False, None), (False, None), (True, True), (False, None)]


def test_pom_unresolved_property_is_none(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text("<project><dependencies><dependency><groupId>g</groupId><artifactId>a</artifactId>"
                   "<version>${missing}</version></dependency></dependencies></project>")
    assert parse_pom(pom) == [("g:a", None)]


def test_catalog_supports_string_and_group_name_forms(tmp_path: Path) -> None:
    toml = tmp_path / "libs.versions.toml"
    toml.write_text('[versions]\nv = "2.1"\n[libraries]\na = "g:a:1.0"\n'
                    'b = { group = "g", name = "b", version.ref = "v" }\n')
    assert parse_version_catalog(toml) == [("g:a", "1.0"), ("g:b", "2.1")]


def test_groovy_tests_count_as_test_evidence(tmp_path: Path) -> None:
    from analyzer.analyze import analyze

    java = tmp_path / "src/main/java/com/example/legacy/order"
    java.mkdir(parents=True)
    (java / "A.java").write_text("package com.example.legacy.order;\npublic class A {}\n")
    groovy = tmp_path / "src/test/groovy/com/example/legacy/order"
    groovy.mkdir(parents=True)
    (groovy / "ATest.groovy").write_text("package com.example.legacy.order\nclass ATest {}\n")
    result = analyze(tmp_path)
    order = result.modules["order"]
    assert (order.has_tests, order.test_classes, order.groovy_test_files) == (True, [], 1)
    assert not [f for f in result.findings if f.kind == "module_without_tests"]


def test_calendar_versions_are_unchecked_not_outdated() -> None:
    snap = DependencySnapshot(as_of="2026-10-01", source="test", entries={
        "d:e": SnapshotEntry(latest_stable_version="20260924.2", latest_major=20260924)})
    out = evaluate("f", [("d:e", "20240325.1")], snap, date_based_min=1900)
    assert [(d.checked, d.outdated) for d in out] == [(False, None)]


def test_testdef_without_class_name_is_attributed_by_component(tmp_path: Path) -> None:
    from analyzer.analyze import analyze

    java = tmp_path / "applications/shop/src/main/java/com/example/legacy/order"
    java.mkdir(parents=True)
    (java / "A.java").write_text("package com.example.legacy.order;\npublic class A {}\n")
    testdef = tmp_path / "applications/shop/testdef"
    testdef.mkdir(parents=True)
    (testdef / "ShopTests.xml").write_text(
        '<test-suite><test-case case-name="load"><entity-xml action="load" entity-xml-url="x"/></test-case>'
        '<test-case case-name="svc"><service-test service-name="createOrder"/></test-case></test-suite>')
    order = analyze(tmp_path).modules["order"]
    assert (order.testdef_suite_files, order.testdef_test_cases, order.has_tests) == (1, 1, True)
