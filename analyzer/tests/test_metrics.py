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
def test_service_fan_in_controller_fan_in_and_used(name: str, result: AnalysisResult, expected: dict[str, Any],
                                                   fqn_of: Any) -> None:
    got, want = result.classes[fqn_of(name)], expected["classes"][name]
    assert got.service_fan_in == want["service_fan_in"]
    assert got.controller_fan_in == want["controller_fan_in"]
    assert got.used == want["used"]


def test_order_services_is_used_despite_zero_java_fan_in(result: AnalysisResult, fqn_of: Any) -> None:
    c = result.classes[fqn_of("OrderServices")]
    assert (c.fan_in, c.service_fan_in, c.controller_fan_in, c.used) == (0, 2, 1, True)


def test_party_controller_is_used_only_through_controller_xml(result: AnalysisResult, fqn_of: Any) -> None:
    c = result.classes[fqn_of("PartyController")]
    assert (c.fan_in, c.service_fan_in, c.controller_fan_in, c.used) == (0, 0, 3, True)
    assert result.classes[fqn_of("PartyLegacyHelper")].used is False


@pytest.mark.parametrize("name", CLASS_NAMES)
def test_size_tier_and_percentiles(name: str, result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    got, want = result.classes[fqn_of(name)], expected["classes"][name]
    assert got.size_tier == want["size_tier"]
    for key in ("loc", "complexity", "fan_in", "fan_out"):
        assert getattr(got, f"{key}_percentile") == pytest.approx(want[f"{key}_percentile"], abs=1e-4), key


def test_extreme_tier_is_a_subset_of_large(result: AnalysisResult, expected: dict[str, Any], fqn_of: Any) -> None:
    extreme = {f.subject for f in result.findings if f.kind == "god_class" and f.tier == "extreme"}
    want = next(s["subjects"] for s in expected["deliberate_smells"] if s["smell"] == "god_class_extreme")
    assert extreme == {fqn_of(n) for n in want} == {fqn_of("OrderServices")}
    large = {f.subject for f in result.findings if f.kind == "god_class" and f.tier == "large"}
    assert large == {fqn_of("LedgerReconciler")}


def test_percentile_rule_is_strictly_lower_share(result: AnalysisResult) -> None:
    pcts = [c.fan_out_percentile for c in result.classes.values()]
    zero_fan_out = [c for c in result.classes.values() if c.fan_out == 0]
    assert zero_fan_out and all(c.fan_out_percentile == 0 for c in zero_fan_out)  # ties at zero stay zero
    assert max(pcts) < 100


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
    flagged = {f.subject for f in result.findings if f.kind == "god_class"}  # both tiers
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
                   "declared_major": d.declared_major, "superseded_by": d.superseded_by,
                   "outdated": d.outdated} for d in result.dependencies), key=key)
    assert got == sorted(expected["dependencies"]["items"], key=key)
    assert sum(bool(d.outdated) for d in result.dependencies) == expected["dependencies"]["outdated_count"]
    assert result.meta.dependency_snapshot_as_of == expected["dependencies"]["snapshot_as_of"]


def test_dependency_status_comes_from_the_committed_snapshot(result: AnalysisResult) -> None:
    spring = next(d for d in result.dependencies if d.coordinate == "org.springframework:spring-core")
    assert spring.declared_version == "4.3.30.RELEASE"  # resolved from ${spring.version}
    assert spring.latest_major is not None and spring.latest_major > 4 and spring.outdated
    servlet = next(d for d in result.dependencies if d.coordinate == "javax.servlet:javax.servlet-api")
    assert servlet.superseded_by == "jakarta.servlet:jakarta.servlet-api" and servlet.outdated


def test_both_dependency_formats_are_read(result: AnalysisResult) -> None:
    assert {d.file for d in result.dependencies} == {"pom.xml", "gradle/libs.versions.toml"}


def test_service_mappings(result: AnalysisResult, expected: dict[str, Any]) -> None:
    got = sorted((m.service, m.engine, m.implementation, m.analyzed, m.line) for m in result.service_mappings)
    want = sorted((m["service"], m["engine"], m["implementation"], m["analyzed"], m["line"])
                  for m in expected["service_mappings"])
    assert got == want


def test_service_reference_status(result: AnalysisResult, expected: dict[str, Any]) -> None:
    got = {m.service: m.reference_status for m in result.service_mappings if m.engine == "java"}
    want = {m["service"]: m["reference_status"] for m in expected["service_mappings"] if m["engine"] == "java"}
    assert got == want
    assert got["syncExternalLedger"] == "out_of_scope"  # unanalysed module: NOT broken


def test_controller_mappings(result: AnalysisResult, expected: dict[str, Any]) -> None:
    got = sorted((m.request, m.implementation, m.line, m.reference_status) for m in result.controller_mappings)
    want = sorted((m["request"], m["implementation"], m["line"], m["reference_status"])
                  for m in expected["controller_mappings"])
    assert got == want


def test_broken_references_are_findings_with_evidence(result: AnalysisResult, expected: dict[str, Any]) -> None:
    got = sorted((f.subject.split(" ", 1)[0] if not f.subject.startswith("controller") else "controller",
                  f.subject.rsplit(" ", 1)[1], f.line, f.value)
                 for f in result.findings if f.kind == "broken_reference")
    want = sorted((b["source"], b["name"], b["line"], b["status"]) for b in expected["broken_references"])
    assert got == want
    assert all(f.file for f in result.findings if f.kind == "broken_reference")


def test_coverage_per_module(result: AnalysisResult, expected: dict[str, Any]) -> None:
    for name, want in expected["modules"].items():
        got = result.modules[name].coverage.model_dump()
        assert got == want["coverage"], name
    assert result.modules["order"].coverage.confidence == "medium"  # 7 of 13 implemented definitions are Java


def test_coverage_confidence_thresholds_come_from_config() -> None:
    cfg = load_config()
    cfg.coverage.high_min_java_share = 0.5
    assert analyze(FIXTURE, cfg=cfg).modules["order"].coverage.confidence == "high"
    cfg.coverage.high_min_java_share, cfg.coverage.medium_min_java_share = 0.9, 0.6
    assert analyze(FIXTURE, cfg=cfg).modules["order"].coverage.confidence == "low"


def test_groovy_is_counted_not_parsed(result: AnalysisResult, expected: dict[str, Any]) -> None:
    want = expected["unanalyzed_files"]
    assert result.unanalyzed_files.groovy_count == want["groovy_count"]
    assert result.unanalyzed_files.groovy_files == want["groovy_files"]
    assert result.unanalyzed_files.service_xml_files == want["service_xml_files"]
    assert result.unanalyzed_files.controller_xml_files == want["controller_xml_files"]
    assert result.unanalyzed_files.controller_event_counts == want["controller_event_counts"]
    assert result.unanalyzed_files.service_engine_counts == want["service_engine_counts"]
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


def test_extreme_threshold_comes_from_config() -> None:
    cfg = load_config()
    cfg.god_class.extreme.min_loc = 400
    cfg.god_class.extreme.min_complexity_above = 50
    tiers = {f.subject.rsplit(".", 1)[1]: f.tier for f in analyze(FIXTURE, cfg=cfg).findings if f.kind == "god_class"}
    assert tiers["LedgerReconciler"] == "extreme"


def test_result_roundtrips_through_the_schema(result: AnalysisResult) -> None:
    assert AnalysisResult.model_validate_json(result.model_dump_json()) == result
