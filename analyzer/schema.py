"""Output contract of the analyzer (one JSON document per run).

Later phases (scoring, roadmap, API, UI) consume exactly these models. Every field is a
deterministic fact computed from source files; nothing here is estimated by an LLM.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SCHEMA_VERSION = "1.0"
Band = Literal["low", "medium", "high"]
SizeTier = Literal["none", "large", "extreme"]
Confidence = Literal["high", "medium", "low"]
DbType = Literal["jdbc", "entity_engine"]
FindingKind = Literal[
    "god_class", "highly_coupled", "module_without_tests", "namespace_mix",
    "module_cycle", "outdated_dependency", "broken_reference",
]


class ClassMetrics(BaseModel):
    """One top-level Java type (one per file in practice)."""

    name: str
    fqn: str
    module: str
    file: str  # relative to the analysed repo root
    loc: int  # code lines in the file: comments and blank lines excluded, package/imports included
    fan_in: int  # distinct other analysed classes that reference this class in Java code
    fan_out: int  # distinct other analysed classes this class references
    service_fan_in: int  # services.xml entries (engine=java) pointing at this class
    controller_fan_in: int  # controller.xml <event type="java"> entries pointing at this class
    used: bool  # fan_in + service_fan_in + controller_fan_in > 0
    complexity: int  # approximate cyclomatic: bodies + decision points
    complexity_band: Band
    size_tier: SizeTier  # large: loc >= 400 and complexity > 50; extreme: loc >= 1500 and complexity > 200 (config)
    # share of analysed classes with a strictly lower value, 0-100 (the largest class is near 100, ties at 0 stay 0)
    loc_percentile: float
    complexity_percentile: float
    fan_in_percentile: float
    fan_out_percentile: float
    depends_on: list[str]  # FQNs
    depended_on_by: list[str]  # FQNs


class Coverage(BaseModel):
    """How much of the module's logic the analyzer can see. Attributed through the module's component directory."""

    component: str  # directory holding most of the module's classes ("" = repo root)
    service_defs_total: int
    service_defs_by_engine: dict[str, int]
    implemented_defs: int  # excludes engines that implement nothing (interface, group)
    java_defs: int
    java_share: float | None  # None when the component defines no services
    groovy_logic_files: int  # Groovy files outside the test directory (counted, not parsed)
    confidence: Confidence


class ModuleMetrics(BaseModel):
    name: str
    classes: list[str]  # FQNs
    class_count: int
    loc: int
    depends_on_modules: dict[str, int]  # module -> number of class-level edges
    module_fan_out: int
    module_fan_in: int
    has_tests: bool  # any test evidence: Java test classes or Groovy test scripts
    test_classes: list[str]  # Java test classes in the matching package
    groovy_test_files: int  # Groovy test scripts in the matching package (counted, not parsed)
    test_method_count: int
    javax_imports: int
    jakarta_imports: int
    namespace_mix: bool
    coverage: Coverage


class DbInstance(BaseModel):
    type: DbType
    file: str
    line: int
    module: str
    class_name: str
    match: str  # e.g. "EntityQuery.use("


class LegacyMarker(BaseModel):
    file: str
    line: int
    module: str
    namespace: str  # javax | jakarta | legacy_framework
    family: str  # servlet, ejb, struts, ...
    import_: str


class Dependency(BaseModel):
    file: str
    coordinate: str
    declared_version: str | None
    declared_major: int | None
    latest_stable_version: str | None  # from the committed snapshot, never fetched at analysis time
    latest_major: int | None
    superseded_by: str | None  # renamed coordinate (e.g. javax.* -> jakarta.*)
    checked: bool  # False when the coordinate is not in the snapshot or no version is declared
    outdated: bool | None


class ServiceMapping(BaseModel):
    service: str
    engine: str
    implementation: str  # "<fqn>#<method>" for java, the script/location otherwise
    analyzed: bool
    file: str
    line: int = 0
    class_found: bool | None = None  # java only: the class exists in the analysed scope
    method_found: bool | None = None
    reference_status: Literal["ok", "method_missing", "class_missing", "out_of_scope", "not_checked"] = "not_checked"


class ControllerMapping(BaseModel):
    """A controller.xml <event type="java"> handler: request-map -> Class#method."""

    request: str
    implementation: str
    file: str
    line: int
    class_found: bool | None = None
    method_found: bool | None = None
    reference_status: Literal["ok", "method_missing", "class_missing", "out_of_scope", "not_checked"] = "not_checked"

class Cycles(BaseModel):
    module_cycles: list[list[str]]  # strongly connected module groups of size > 1
    class_cycles: list[list[str]]  # FQNs


class Finding(BaseModel):
    """One concrete issue with evidence."""

    kind: FindingKind
    subject: str  # class, module or dependency coordinate
    detail: str
    file: str | None = None
    line: int | None = None
    metric: str | None = None
    value: float | str | None = None
    tier: str | None = None  # god_class: "large" or "extreme"


class DbSummary(BaseModel):
    total: int
    jdbc: int
    entity_engine: int
    instances: list[DbInstance]


class Unanalyzed(BaseModel):
    groovy_count: int
    groovy_files: list[str]
    service_xml_files: list[str]
    service_engine_counts: dict[str, int]
    controller_xml_files: list[str]
    controller_event_counts: dict[str, int]  # by event type (java is analysed; service/groovy/simple are not)
    report_status: Literal["not_analyzed"] = "not_analyzed"


class Totals(BaseModel):
    main_java_classes: int
    modules: int
    main_java_loc: int
    test_classes: int
    dependencies_declared: int
    dependencies_checked: int  # coordinates found in the bundled table with a parseable version


class RunMeta(BaseModel):
    schema_version: str = SCHEMA_VERSION
    name: str
    repo_path: str
    scope: list[str]
    analyzer: str
    runtime_seconds: float
    config_file: str
    dependency_snapshot_as_of: str
    parse_errors: list[str]


class AnalysisResult(BaseModel):
    meta: RunMeta
    totals: Totals
    modules: dict[str, ModuleMetrics]
    classes: dict[str, ClassMetrics]  # keyed by FQN
    cycles: Cycles
    db_coupling: DbSummary
    legacy_markers: list[LegacyMarker]
    dependencies: list[Dependency]
    service_mappings: list[ServiceMapping]
    controller_mappings: list[ControllerMapping]
    unanalyzed_files: Unanalyzed
    findings: list[Finding]
