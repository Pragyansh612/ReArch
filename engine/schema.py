"""Output contract of the scoring engine (Phase 3). Every number carries the breakdown that reconstructs it.

All figures are deterministic functions of (analyzer output, config/assumptions.yaml, criticality overrides).
The assumptions are ILLUSTRATIVE and are echoed into the output so they can be shown next to every yen figure.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from engine.config import Criterion, Priorities, Strategy

SCHEMA_VERSION = "1.0"


# --- technical health --------------------------------------------------------------------------------
class HealthComponent(BaseModel):
    key: str
    label: str
    raw: float  # the measured value, in `raw_unit`
    raw_unit: str
    normalized: float  # 0 (good) .. 1 (bad)
    weight: float
    contribution_points: float  # 100 x weight x normalized, rounded to 4 decimals: points LOST from 100
    how: str  # plain-English formula for this component


class ModuleHealth(BaseModel):
    score: float  # = round(100 - sum(contribution_points), 4)
    components: list[HealthComponent]
    top_drivers: list[str]  # component keys, biggest contribution first (top 3)


class HotspotComponent(BaseModel):
    key: str
    value: float  # 0..100
    weight: float
    contribution: float  # weight x value, rounded to 4 decimals


class Hotspot(BaseModel):
    fqn: str
    module: str
    file: str
    loc: int
    complexity: int
    size_tier: str
    score: float  # = round(sum(contribution), 4)
    components: list[HotspotComponent]
    flags: list[str]


# --- business criticality ----------------------------------------------------------------------------
class CriticalityInputs(BaseModel):
    java_cross_module_fan_in: int
    service_fan_in: int
    controller_fan_in: int
    inbound_total: int
    inbound_share: float  # module share of the estate's inbound references
    data_writes: int
    write_share: float
    score: float  # inbound_weight x inbound_share + write_weight x write_share


class Criticality(BaseModel):
    value: int  # 1..3, the figure used downstream
    source: Literal["heuristic", "override"]
    heuristic_value: int  # what the heuristic proposed (kept even when overridden)
    inputs: CriticalityInputs
    override_reason: str | None = None
    status: Literal["proposed", "confirmed_by_override"] = "proposed"


# --- strategy options --------------------------------------------------------------------------------
class EffortLine(BaseModel):
    label: str
    days: float
    formula: str


class Component(BaseModel):
    key: str
    measure: float  # 0..1 measure (or raw value for value components)
    weight: float
    contribution: float


class StrategyOption(BaseModel):
    strategy: Strategy
    eligible: bool
    ineligible_reason: str | None = None
    multipliers: dict[str, float] = {}
    effort_lines: list[EffortLine] = []
    effort_days: float | None = None  # = round(sum of effort_lines, 4)
    cost_jpy: int | None = None  # = round(effort_days x daily_rate_jpy)
    duration_months: float | None = None  # = round(effort_days / (team_size x working_days_per_month), 4)
    team_size: float | None = None
    risk_score: float | None = None  # = round(min(100, base_risk x (1 + exposure_gain x sum(risk_components.contribution))), 4)
    base_risk: float | None = None
    risk_components: list[Component] = []
    long_term_value: float | None = None  # = round(debt_reduction x burden, 4)
    debt_reduction: float | None = None
    burden: float | None = None


# --- priorities and choice ---------------------------------------------------------------------------
class CriterionScore(BaseModel):
    criterion: Criterion
    raw: float  # cost_jpy, risk_score, duration_months or long_term_value
    goodness: float  # 0..1 on the absolute scale of the criterion (see config `scoring`)
    weight: float
    contribution: float  # 100 x weight x goodness, rounded to 4 decimals


class ScoredStrategy(BaseModel):
    strategy: Strategy
    score: float  # = round(sum(criteria.contribution), 4)
    criteria: list[CriterionScore]


class StrategyChoice(BaseModel):
    profile: str
    weights: Priorities
    chosen: Strategy
    score: float
    runner_up: Strategy | None
    runner_up_score: float | None
    margin: float | None  # score - runner_up_score
    close_call: bool
    ranking: list[ScoredStrategy]  # eligible options, best first


class Flip(BaseModel):
    """The smallest single-assumption change that flips this module's recommendation."""

    parameter: str  # daily_rate_jpy | base_days_per_kloc.<strategy> | priority.<criterion>
    current_value: float
    flip_value: float | None  # None when no flip exists inside the searched range
    change_pct: float | None  # |flip - current| / current x 100 (absolute points x 100 when current is 0)
    new_strategy: Strategy | None
    note: str


class ModuleReport(BaseModel):
    module: str
    loc: int
    kloc: float
    health: ModuleHealth
    criticality: Criticality
    confidence: Literal["high", "medium", "low"]
    java_share: float | None
    inbound_references: dict[str, int]  # references into the module by type; any non-zero value makes retire ineligible
    options: list[StrategyOption]
    choices: dict[str, StrategyChoice]  # by profile name (all presets plus a custom profile if given)
    sensitivity: list[Flip]  # for the selected profile, smallest change first


class ProfileTotals(BaseModel):
    profile: str
    weights: Priorities
    strategy_by_module: dict[str, Strategy]
    total_effort_days: float
    total_cost_jpy: int
    total_duration_months: float  # sum over modules: one shared programme team works them in sequence
    close_calls: list[str]


class RecommendationMeta(BaseModel):
    schema_version: str = SCHEMA_VERSION
    analysis_name: str
    analyzer: str
    selected_profile: str
    engine: str = "rearch-engine 0.1.0"
    notes: list[str]


class Recommendation(BaseModel):
    meta: RecommendationMeta
    assumptions: dict[str, Any]  # echo of every rate/weight used, flagged ILLUSTRATIVE
    modules: dict[str, ModuleReport]
    hotspots: list[Hotspot]
    estate: dict[str, ProfileTotals]  # by profile name
