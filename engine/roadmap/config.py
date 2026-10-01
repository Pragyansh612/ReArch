"""Typed view of the `roadmap` section of config/assumptions.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from analyzer.config import DEFAULT_CONFIG
from engine.config import Strategy


class QuickWin(BaseModel):
    max_risk: float
    max_months: float


class Cicd(BaseModel):
    base_days: float
    days_per_package: float


class Observability(BaseModel):
    base_days: float
    days_per_kloc: float


class Facade(BaseModel):
    base_days: float
    days_per_package: float


class Foundations(BaseModel):
    team_people: int
    cicd: Cicd
    observability: Observability
    facade: Facade
    weak_test_gap: float
    required_by: dict[str, list[Strategy]]
    strategy_rank: dict[Strategy, int]


class Requirement(BaseModel):
    module: str
    min_strategy: Strategy
    min_loc_share: float


class Unlock(BaseModel):
    id: str
    name: str
    kind: str
    description: str
    requires: list[Requirement]


class RoadmapConfig(BaseModel):
    teams: int
    team_size_people: int
    yearly_budget_cap_jpy: int | None
    search_horizon_months: int
    wave_name_template: str
    quick_win: QuickWin
    foundations: Foundations
    unlocks: list[Unlock]

    @property
    def capacity(self) -> int:
        return self.teams * self.team_size_people


def load_roadmap_config(path: Path = DEFAULT_CONFIG) -> RoadmapConfig:
    return RoadmapConfig(**yaml.safe_load(path.read_text(encoding="utf-8"))["roadmap"])
