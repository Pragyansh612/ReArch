"""Output contract of the roadmap (Phase 4). Gantt-ready: every item has a wave, start and end month, people, cost, events."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from engine.config import Priorities, Strategy

SCHEMA_VERSION = "1.0"


class ReasonCode(BaseModel):
    code: str  # DEPENDS_ON | ENTANGLED_WITH | NEEDS_SAFETY_NET | NEEDS_CICD | NEEDS_OBSERVABILITY | NEEDS_FACADE | ...
    detail: str


class CutoverEvent(BaseModel):
    month: int
    hours: float


class Item(BaseModel):
    id: str
    wave: int
    kind: Literal["foundation", "package"]
    name: str
    package_id: str | None
    module: str | None
    strategy: Strategy | None
    start_month: int  # 1-based, inclusive
    end_month: int  # inclusive
    people: int  # capacity it occupies for the whole duration
    lane: int  # display row for the Gantt chart (rows are not capacity)
    team: str
    effort_days: float
    cost_jpy: int
    monthly_spend_jpy: list[int]  # one entry per month from start_month to end_month; sums to cost_jpy
    cutover_events: list[CutoverEvent]
    depends_on: list[str]
    reason_codes: list[ReasonCode]  # never empty
    formula: str | None = None  # foundations: how the effort was estimated


class Wave(BaseModel):
    number: int  # 0 = foundations; the last wave is "What modernization unlocks" (no work items)
    name: str
    start_month: int | None
    end_month: int | None
    item_ids: list[str]
    cost_jpy: int
    peak_people: int


class Unscheduled(BaseModel):
    id: str
    name: str
    reason_codes: list[ReasonCode]


class Downgrade(BaseModel):
    package_id: str
    name: str
    unconstrained: Strategy
    constrained: Strategy
    score_lost: float  # the package's own 0-100 score lost
    weighted_score_lost: float  # that loss times the package's share of the estate's do-nothing TCO
    migration_cost_saved_jpy: int
    reason: str


class PortfolioChoice(BaseModel):
    package_id: str
    strategy: Strategy
    score: float
    weight: float  # the package's share of the estate's 5-year do-nothing (retain) TCO: its value at stake
    migration_cost_jpy: int


class Portfolio(BaseModel):
    total_score: float  # retain-TCO-weighted mean of the chosen options' scores (0-100)
    total_unweighted_score: float  # plain sum of the chosen options' scores, for reference
    total_migration_cost_jpy: int
    choices: list[PortfolioChoice]
    strategy_mix: dict[str, int]


class PortfolioSelection(BaseModel):
    profile: str
    weights: Priorities
    budget_ceiling_jpy: int
    method: str
    objective: str
    budget_binding: bool  # True when the unconstrained portfolio exceeds the budget
    unconstrained: Portfolio
    constrained: Portfolio
    downgrades: list[Downgrade]


class Opportunity(BaseModel):
    id: str
    name: str
    kind: str
    description: str
    status: Literal["unlocked", "not_unlocked", "module_not_analysed"]
    requirements: list[str]  # plain-English
    prerequisite_packages: list[str]
    available_from_month: int | None  # month after the last prerequisite finishes
    blocked_by: list[str]  # packages (or modules) that do not meet the requirement


class QuarterPoint(BaseModel):
    quarter: int
    month_end: int
    programme_spend_jpy: int  # migration + foundations spent in the quarter
    roadmap_cumulative_cost_jpy: int  # everything paid since month 1 under the roadmap
    retain_cumulative_cost_jpy: int  # everything paid since month 1 doing nothing
    net_cumulative_jpy: int  # retain - roadmap (positive = ahead of doing nothing)
    roadmap_annual_run_rate_jpy: int  # yearly maintenance + run + change cost at the end of the quarter
    retain_annual_run_rate_jpy: int


class KpiPoint(BaseModel):
    quarter: int
    month_end: int
    value: float


class KpiTrajectory(BaseModel):
    objective: str
    label: str
    unit: str
    modelled: bool
    current: float
    target: float
    note: str
    points: list[KpiPoint]
    target_reached_quarter: int | None


class Economics(BaseModel):
    horizon_months: int
    discount_rate: float
    quarters: list[QuarterPoint]
    total_programme_cost_jpy: int  # migration + foundations scheduled inside the horizon
    payback_quarter: int | None  # first quarter-end at which cumulative cost is no higher than retain's; None if never
    npv_vs_retain_jpy: int  # present value of (retain - roadmap) monthly flows over the horizon
    peak_investment_jpy: int  # largest cumulative shortfall against retain
    peak_investment_quarter: int | None
    kpis: list[KpiTrajectory]


class Headline(BaseModel):
    """A deterministic sentence built from the numbers in `numbers` (no LLM). The UI's executive summary."""

    id: str
    kind: str
    text: str
    numbers: dict[str, float | int | str]


class RoadmapMeta(BaseModel):
    schema_version: str = SCHEMA_VERSION
    analysis_name: str
    profile: str
    scenario_client: str
    capacity_people: int
    teams: int
    yearly_budget_cap_jpy: int | None
    finish_month: int | None
    notes: list[str]


class Roadmap(BaseModel):
    meta: RoadmapMeta
    portfolio: PortfolioSelection
    waves: list[Wave]
    items: list[Item]
    unscheduled: list[Unscheduled]
    retained_packages: list[str]
    unlocks: list[Opportunity]
    economics: Economics
    headlines: list[Headline]
    assumptions: dict[str, Any]
