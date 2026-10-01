"""Typed view of the `engine` section of config/assumptions.yaml, plus criticality overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from analyzer.config import DEFAULT_CONFIG

Strategy = Literal["rehost", "replatform", "refactor", "rearchitect", "retire"]
Criterion = Literal["cost", "risk", "speed", "long_term_value"]
CRITERIA: tuple[Criterion, ...] = ("cost", "risk", "speed", "long_term_value")
DEFAULT_OVERRIDES = DEFAULT_CONFIG.parent / "criticality_overrides.yaml"
_TOLERANCE = 1e-9


def _must_sum_to_one(weights: dict[str, float], what: str) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > _TOLERANCE:
        raise ValueError(f"{what} must sum to 1, got {total}")


class Priorities(BaseModel):
    """Client weights over the four criteria; they sum to 1."""

    cost: float
    risk: float
    speed: float
    long_term_value: float

    @model_validator(mode="after")
    def _sum(self) -> Priorities:
        _must_sum_to_one(self.model_dump(), "priority weights")
        return self


class MultiplierRule(BaseModel):
    max: float
    sensitivity: dict[Strategy, float]


class TestOverheadRule(BaseModel):
    base: dict[Strategy, float]
    untested_extra: float


class RiskRule(BaseModel):
    base: dict[Strategy, float]
    exposure_gain: float
    factor_weights: dict[str, float]
    confidence_gap: dict[str, float]

    @model_validator(mode="after")
    def _sum(self) -> RiskRule:
        _must_sum_to_one(self.factor_weights, "risk factor weights")
        return self


class ValueRule(BaseModel):
    debt_reduction: dict[Strategy, float]
    debt_weight: float
    maintenance_kloc_cap: float


class PriorityConfig(BaseModel):
    default: str
    presets: dict[str, Priorities]


class HealthRule(BaseModel):
    weights: dict[str, float]
    test_target_per_kloc: float
    db_calls_per_kloc_cap: float

    @model_validator(mode="after")
    def _sum(self) -> HealthRule:
        _must_sum_to_one(self.weights, "health weights")
        return self


class HotspotRule(BaseModel):
    top_n: int
    weights: dict[str, float]

    @model_validator(mode="after")
    def _sum(self) -> HotspotRule:
        _must_sum_to_one(self.weights, "hotspot weights")
        return self


class CriticalityRule(BaseModel):
    inbound_weight: float
    write_weight: float
    high_min_score: float
    medium_min_score: float
    write_matches: list[str]
    jdbc_counts_as_write: bool


class ScoringRule(BaseModel):
    cost_ceiling_jpy: float
    duration_ceiling_months: float


class SensitivityRule(BaseModel):
    range_factor: float
    steps: int


class EngineConfig(BaseModel):
    currency: str
    daily_rate_jpy: float
    base_days_per_kloc: dict[Strategy, float]
    strategies: list[Strategy]
    working_days_per_month: float
    team_size: dict[Strategy, float]
    complexity_multiplier: MultiplierRule
    test_overhead: TestOverheadRule
    coverage_uncertainty_buffer: dict[str, float]
    safety_net_days_per_kloc: float
    risk: RiskRule
    long_term_value: ValueRule
    priorities: PriorityConfig
    scoring: ScoringRule
    close_call_margin: float
    health: HealthRule
    hotspots: HotspotRule
    criticality: CriticalityRule
    sensitivity: SensitivityRule


def load_engine_config(path: Path = DEFAULT_CONFIG) -> EngineConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EngineConfig(currency=raw["currency"], daily_rate_jpy=raw["daily_rate_jpy"],
                        base_days_per_kloc=raw["base_days_per_kloc"], **raw["engine"])


def parse_profile(text: str, cfg: EngineConfig) -> tuple[str, Priorities]:
    """A preset name, or custom weights like `cost=0.4,risk=0.3,speed=0.2,long_term_value=0.1`."""
    if text in cfg.priorities.presets:
        return text, cfg.priorities.presets[text]
    try:
        pairs = dict(item.split("=") for item in text.split(","))
        return "custom", Priorities(**{k.strip(): float(v) for k, v in pairs.items()})
    except (ValueError, TypeError) as exc:
        names = ", ".join(cfg.priorities.presets)
        raise ValueError(f"profile must be one of [{names}] or cost=..,risk=..,speed=..,long_term_value=.. "
                         f"(sum 1): {exc}") from exc


class Override(BaseModel):
    module: str
    criticality: int
    reason: str

    @model_validator(mode="after")
    def _valid(self) -> Override:
        if self.criticality not in (1, 2, 3):
            raise ValueError(f"override for {self.module}: criticality must be 1, 2 or 3")
        if len(self.reason.strip()) < 10:
            raise ValueError(f"override for {self.module}: a written reason is required")
        return self


def load_overrides(analysis_name: str, path: Path = DEFAULT_OVERRIDES) -> dict[str, Override]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = (raw.get("analyses") or {}).get(analysis_name) or []
    return {o.module: o for o in (Override(**item) for item in items)}
