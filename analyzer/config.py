"""Typed view of the `analysis` and `dependency_table` sections of config/assumptions.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "assumptions.yaml"


class Bands(BaseModel):
    low_max: int
    medium_max: int


class GodClassRule(BaseModel):
    min_loc: int
    min_complexity_above: int


class CouplingRule(BaseModel):
    min_fan_in: int
    min_fan_out: int


class CallPattern(BaseModel):
    method: str
    receiver: str | None = None


class DbRules(BaseModel):
    ignore_classes: list[str]
    jdbc: list[CallPattern]
    entity_engine: list[CallPattern]


class MarkerRules(BaseModel):
    javax_migrating: list[str]
    legacy_frameworks: dict[str, list[str]]


class DependencyTable(BaseModel):
    as_of: str
    min_current_major: dict[str, int]


class AnalysisConfig(BaseModel):
    module_roots: list[str]
    main_java_dir: str
    test_java_dir: str
    test_groovy_dir: str
    services_dir_name: str
    skip_dirs: list[str]
    complexity_bands: Bands
    god_class: GodClassRule
    highly_coupled: CouplingRule
    db_coupling: DbRules
    legacy_markers: MarkerRules
    dependency_table: DependencyTable


def load_config(path: Path = DEFAULT_CONFIG) -> AnalysisConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AnalysisConfig(**raw["analysis"], dependency_table=raw["dependency_table"])
