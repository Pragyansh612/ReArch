"""Output contract of the analyzer (one JSON document per run).

Later phases (scoring, roadmap, API, UI) consume exactly these models. Every field is a
deterministic fact computed from source files; nothing here is estimated by an LLM.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SCHEMA_VERSION = "1.0"
Band = Literal["low", "medium", "high"]
DbType = Literal["jdbc", "entity_engine"]
FindingKind = Literal[
    "god_class", "highly_coupled", "module_without_tests", "namespace_mix",
    "module_cycle", "outdated_dependency",
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
    used: bool  # fan_in + service_fan_in > 0
    complexity: int  # approximate cyclomatic: bodies + decision points
    complexity_band: Band
    depends_on: list[str]  # FQNs
    depended_on_by: list[str]  # FQNs


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
    min_current_major: int | None
    checked: bool  # False when the coordinate is not in the bundled table or no version is declared
    outdated: bool | None


class ServiceMapping(BaseModel):
    service: str
    engine: str
    implementation: str  # "<fqn>#<method>" for java, the script/location otherwise
    analyzed: bool
    file: str
    class_found: bool | None = None  # java only: the class exists in the analysed scope
    method_found: bool | None = None


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
    dependency_table_as_of: str
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
    unanalyzed_files: Unanalyzed
    findings: list[Finding]
