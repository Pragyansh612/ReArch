"""One test per metric, each asserting the value in fixtures/expected.json (the oracle)."""

from __future__ import annotations

from typing import Any

import pytest

from analyzer.analyze import analyze
from analyzer.config import load_config
from analyzer.schema import AnalysisResult
from analyzer.tests.conftest import FIXTURE

CLASS_NAMES = [
    "BillingException", "InvoiceItem", "InvoiceService", "LedgerReconciler", "PaymentCalculator",
    "StatementFormatter", "Delegator", "EntityQuery", "GenericValue", "StringUtil", "Order", "OrderItem",
    "OrderReadHelper", "OrderServices", "OrderStatus", "ShoppingCart", "Party", "PartyController",
    "PartyLegacyHelper", "PartyService",
]


def test_expected_lists_every_class(expected: dict[str, Any]) -> None:
    assert sorted(expected["classes"]) == sorted(CLASS_NAMES)


def test_no_parse_errors(result: AnalysisResult) -> None:
    assert result.meta.parse_errors == []


def test_totals(result: AnalysisResult, expected: dict[str, Any]) -> None:
    got = result.totals.model_dump()
    assert {k: got[k] for k in expected["totals"]} == expected["totals"]


@pytest.mark.parametrize("name", CLASS_NAMES)
def test_loc(name: str, result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    assert result.classes[fqn_of(name)].loc == expected["classes"][name]["loc"]


@pytest.mark.parametrize("name", CLASS_NAMES)
def test_fan_in(name: str, result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    assert result.classes[fqn_of(name)].fan_in == expected["classes"][name]["fan_in"]


@pytest.mark.parametrize("name", CLASS_NAMES)
def test_fan_out_and_edges(name: str, result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    got, want = result.classes[fqn_of(name)], expected["classes"][name]
    assert got.fan_out == want["fan_out"]
    assert sorted(got.depends_on) == sorted(fqn_of(n) for n in want["depends_on"])
    assert sorted(got.depended_on_by) == sorted(fqn_of(n) for n in want["depended_on_by"])


@pytest.mark.parametrize("name", CLASS_NAMES)
def test_service_fan_in_and_used(name: str, result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    got, want = result.classes[fqn_of(name)], expected["classes"][name]
    assert got.service_fan_in == want["service_fan_in"]
    assert got.used == want["used"]


def test_order_services_is_used_despite_zero_java_fan_in(result: AnalysisResult, fqn_of: Any) -> None:
    c = result.classes[fqn_of("OrderServices")]
    assert (c.fan_in, c.service_fan_in, c.used) == (0, 2, True)


@pytest.mark.parametrize("name", CLASS_NAMES)
def test_complexity_and_band(name: str, result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    got, want = result.classes[fqn_of(name)], expected["classes"][name]
    assert got.complexity == want["complexity"]
    assert got.complexity_band == want["complexity_band"]


def test_module_metrics(result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    assert sorted(result.modules) == sorted(expected["modules"])
    for name, want in expected["modules"].items():
        got = result.modules[name]
        assert got.class_count == want["class_count"]
        assert got.loc == want["loc"]
        assert sorted(got.classes) == sorted(fqn_of(n) for n in want["classes"])
        assert got.depends_on_modules == want["depends_on_modules"]
        assert (got.module_fan_in, got.module_fan_out) == (want["module_fan_in"], want["module_fan_out"])


def test_test_presence_per_module(result: AnalysisResult, expected: dict[str, Any]) -> None:
    for name, want in expected["modules"].items():
        assert result.modules[name].has_tests == want["has_tests"], name
        assert result.modules[name].test_classes == want["test_classes"], name


def test_test_methods_are_counted(result: AnalysisResult) -> None:
    assert result.modules["billing"].test_method_count == 2
    assert result.modules["party"].test_method_count == 1


def test_god_class_boundary(result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    flagged = {f.subject for f in result.findings if f.kind == "god_class"}
    wanted = next(s["subjects"] for s in expected["deliberate_smells"] if s["smell"] == "god_class")
    assert flagged == {fqn_of(n) for n in wanted}
    assert fqn_of("LedgerReconciler") in flagged       # LOC 400, complexity 51: exactly on the thresholds
    assert fqn_of("StatementFormatter") not in flagged  # LOC 399, complexity 50: one short of both


def test_highly_coupled(result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    flagged = {f.subject for f in result.findings if f.kind == "highly_coupled"}
    wanted = next(s["subjects"] for s in expected["deliberate_smells"] if s["smell"] == "highly_coupled_service")
    assert flagged == {fqn_of(n) for n in wanted}


def test_db_coupling_totals(result: AnalysisResult, expected: dict[str, Any]) -> None:
    want = expected["db_coupling"]
    assert (result.db_coupling.total, result.db_coupling.jdbc, result.db_coupling.entity_engine) == (
        want["total"], want["jdbc"], want["entity_engine"])


def test_db_coupling_instances_have_exact_file_and_line(result: AnalysisResult, expected: dict[str, Any]) -> None:
    got = sorted((d.type, d.file, d.line, d.module, d.class_name, d.match) for d in result.db_coupling.instances)
    want = sorted((d["type"], d["file"], d["line"], d["module"], d["class"], d["match"])
                  for d in expected["db_coupling"]["instances"])
    assert got == want


def test_legacy_markers(result: AnalysisResult, expected: dict[str, Any]) -> None:
    got = sorted((m.file, m.line, m.module, m.namespace, m.family, m.import_) for m in result.legacy_markers)
    want = sorted((m["file"], m["line"], m["module"], m["namespace"], m["family"], m["import"])
                  for m in expected["legacy_markers"]["instances"])
    assert got == want


def test_namespace_mix(result: AnalysisResult, expected: dict[str, Any]) -> None:
    for name, want in expected["modules"].items():
        got = result.modules[name]
        assert (got.javax_imports, got.jakarta_imports, got.namespace_mix) == (
            want["javax_imports"], want["jakarta_imports"], want["namespace_mix"]), name


def test_outdated_dependencies(result: AnalysisResult, expected: dict[str, Any]) -> None:
    key = lambda d: (d["file"], d["coordinate"])
    got = sorted(({"file": d.file, "coordinate": d.coordinate, "declared_version": d.declared_version,
                   "declared_major": d.declared_major, "min_current_major": d.min_current_major,
                   "outdated": d.outdated} for d in result.dependencies), key=key)
    assert got == sorted(expected["dependencies"]["items"], key=key)
    assert sum(bool(d.outdated) for d in result.dependencies) == expected["dependencies"]["outdated_count"]
    assert result.meta.dependency_table_as_of == expected["dependencies"]["table_as_of"]


def test_both_dependency_formats_are_read(result: AnalysisResult) -> None:
    files = {d.file for d in result.dependencies}
    assert files == {"pom.xml", "gradle/libs.versions.toml"}
    spring = next(d for d in result.dependencies if d.coordinate == "org.springframework:spring-core")
    assert spring.declared_version == "4.3.30.RELEASE"  # resolved from ${spring.version}


def test_service_mappings(result: AnalysisResult, expected: dict[str, Any]) -> None:
    got = sorted((s.service, s.engine, s.implementation, s.analyzed) for s in result.service_mappings)
    want = sorted((s["service"], s["engine"], s["implementation"], s["analyzed"]) for s in expected["service_mappings"])
    assert got == want
    assert all(s.class_found and s.method_found for s in result.service_mappings if s.engine == "java")


def test_groovy_is_counted_not_parsed(result: AnalysisResult, expected: dict[str, Any]) -> None:
    want = expected["unanalyzed_files"]
    assert result.unanalyzed_files.groovy_count == want["groovy_count"]
    assert result.unanalyzed_files.groovy_files == want["groovy_files"]
    assert result.unanalyzed_files.service_xml_files == want["service_xml_files"]
    assert result.unanalyzed_files.report_status == "not_analyzed"
    assert not any(c.file.endswith(".groovy") for c in result.classes.values())


def test_cycles(result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    assert result.cycles.module_cycles == expected["cycles"]["module_cycles"]
    assert result.cycles.class_cycles == sorted(sorted(fqn_of(n) for n in grp)
                                                for grp in expected["cycles"]["class_cycles"])


# --- traps from docs/fixture.md -------------------------------------------------------------------

def test_trap_comment_and_string_mentions_are_not_db_coupling(result: AnalysisResult) -> None:
    assert not [d for d in result.db_coupling.instances if d.class_name == "PaymentCalculator"]


def test_trap_javadoc_mention_is_not_a_dependency(result: AnalysisResult, fqn_of: Any) -> None:
    deps = result.classes[fqn_of("PaymentCalculator")].depends_on
    assert deps == [fqn_of("InvoiceItem")]


def test_trap_jdk_javax_is_not_a_marker(result: AnalysisResult) -> None:
    assert not [m for m in result.legacy_markers if "javax.sql" in m.import_]


def test_trap_stub_api_is_not_db_coupling(result: AnalysisResult) -> None:
    assert not [d for d in result.db_coupling.instances if d.class_name in ("EntityQuery", "Delegator")]


def test_trap_high_fan_in_alone_is_not_coupled(result: AnalysisResult, fqn_of: Any) -> None:
    flagged = {f.subject for f in result.findings if f.kind == "highly_coupled"}
    assert fqn_of("StringUtil") not in flagged
    assert fqn_of("GenericValue") not in flagged


# --- the config really drives the analysis ----------------------------------------------------------

def test_thresholds_come_from_config() -> None:
    cfg = load_config()
    cfg.god_class.min_loc = 399
    cfg.god_class.min_complexity_above = 49
    flagged = {f.subject for f in analyze(FIXTURE, cfg=cfg).findings if f.kind == "god_class"}
    assert any(s.endswith("StatementFormatter") for s in flagged)


def test_result_roundtrips_through_the_schema(result: AnalysisResult) -> None:
    assert AnalysisResult.model_validate_json(result.model_dump_json()) == result
