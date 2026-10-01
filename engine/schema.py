"""Output contract of the scoring engine. Every number carries the breakdown that reconstructs it.

All figures are deterministic functions of (analyzer output, config/assumptions.yaml, config/client_scenario.yaml).
The assumptions are ILLUSTRATIVE and the scenario is FICTIONAL; both are echoed into the output so they can be
shown next to every yen figure.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from engine.config import Criterion, Priorities, Strategy

SCHEMA_VERSION = "3.0"


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


# --- options -----------------------------------------------------------------------------------------
class EffortLine(BaseModel):
    label: str
    days: float
    formula: str


class Component(BaseModel):
    key: str
    measure: float  # 0..1
    weight: float
    contribution: float  # weight x measure, rounded to 4 decimals


class CashFlowYear(BaseModel):
    year: int
    migration_jpy: int
    run_jpy: int
    maintenance_jpy: int
    change_jpy: int  # cost of the year's change requests (health dependent)
    total_jpy: int  # migration + run + maintenance + change


class Tco(BaseModel):
    """tco = migration + sum over years (run + maintenance + change); all whole yen, so it reconstructs exactly."""

    horizon_years: int
    discount_rate: float
    baseline_maintenance_jpy_per_year: float  # the do-nothing yearly maintenance this unit costs today
    baseline_run_jpy_per_year: float
    baseline_change_jpy_per_year: float
    steady_state_maintenance_jpy: int  # yearly figures once the migration is complete
    steady_state_run_jpy: int
    steady_state_change_jpy: int
    yearly: list[CashFlowYear]
    migration_total_jpy: int
    run_total_jpy: int
    maintenance_total_jpy: int
    change_total_jpy: int
    change_savings_vs_retain_jpy: int  # the change-cost benefit line: retain's change cost minus this option's
    tco_jpy: int
    npv_cost_jpy: int  # present value of all cash outflows, year-end discounting
    savings_vs_retain_jpy: int  # retain tco - tco (positive = cheaper than doing nothing over the horizon)
    npv_vs_retain_jpy: int  # retain npv_cost - npv_cost
    payback_year: int | None  # first year cumulative cost <= retain's; None for retain or if never within the horizon


class ObjectiveContribution(BaseModel):
    objective: str
    weight: float  # the client's weight for this objective
    effect: float  # share of the gap this strategy can close (config)
    counted: bool = True  # False for the objective monetised in TCO (change cost): left out of the value to avoid double counting
    contribution: float  # weight x effect / (sum of counted weights); 0 when not counted


class ValueBreakdown(BaseModel):
    """value = min(100, debt_reduction x burden x criticality_weight x objective_fit), rounded to 4 decimals."""

    debt_reduction: float
    burden: float
    criticality: int
    criticality_weight: float
    objective_fit: float  # = sum of objectives.contribution
    objectives: list[ObjectiveContribution]
    uncapped: float
    value: float


class StrategyOption(BaseModel):
    strategy: Strategy
    eligible: bool
    ineligible_reason: str | None = None
    feasible: bool = True
    infeasible_reasons: list[str] = []
    multipliers: dict[str, float] = {}
    effort_lines: list[EffortLine] = []
    effort_days: float | None = None  # = round(sum of effort_lines, 4)
    migration_cost_jpy: int | None = None  # = round(effort_days x daily_rate_jpy); 0 for retain
    duration_months: float | None = None  # = round(effort_days / (team_size x working_days_per_month), 4)
    team_size: float | None = None
    cutover_approach: str | None = None  # none | big_bang | incremental
    cutover_events: int | None = None  # slices (incremental) or 1 (big bang)
    cutover_hours_per_event: float | None = None  # the client's downtime limit applies to each event
    cutover_total_hours: float | None = None
    risk_score: float | None = None
    base_risk: float | None = None
    risk_components: list[Component] = []
    value: ValueBreakdown | None = None
    tco: Tco | None = None


# --- priorities and choice ---------------------------------------------------------------------------
class CriterionScore(BaseModel):
    criterion: Criterion
    raw: float  # tco_jpy, risk_score, duration_months or value
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
    ranking: list[ScoredStrategy]  # selectable (eligible and feasible) options, best first


class Flip(BaseModel):
    """The smallest single-assumption change that flips this unit's recommendation."""

    parameter: str  # daily_rate_jpy | base_days_per_kloc.<strategy> | priority.<criterion>
    current_value: float
    flip_value: float | None  # None when no flip exists inside the searched range
    change_pct: float | None
    new_strategy: Strategy | None
    note: str


class Overtake(BaseModel):
    strategy: Strategy
    breakeven_jpy_per_year: float | None  # yearly maintenance spend at which this strategy overtakes the chosen one
    multiple_of_baseline: float | None
    direction: Literal["higher", "lower"] | None  # spend must rise or fall from the baseline


class Breakeven(BaseModel):
    """How wrong the maintenance baseline would have to be to change the recommendation (selected profile)."""

    baseline_jpy_per_year: float
    chosen: Strategy
    overtaking: list[Overtake]  # every other selectable strategy
    retain_stops_being_best_jpy_per_year: float | None  # only meaningful when retain is not already losing
    retain_loses_to_every_alternative_jpy_per_year: float | None
    note: str


class WorkPackageReport(BaseModel):
    id: str
    module: str
    kind: str  # cycle | god_class_cluster | remainder
    name: str
    classes: list[str]
    cycle_modules: list[str]
    loc: int
    kloc: float
    health: ModuleHealth
    confidence: Literal["high", "medium", "low"]
    inbound_references: dict[str, int]  # from outside the package; any non-zero value makes retire ineligible
    options: list[StrategyOption]  # always includes `retain`
    choices: dict[str, StrategyChoice]  # by profile name
    sensitivity: list[Flip]  # for the selected profile, smallest change first
    breakeven: Breakeven | None  # for the selected profile
    maintenance_baseline_jpy_per_year: float
    change_requests_per_year: float


class ModuleRollup(BaseModel):
    """A module's work packages under one profile; every figure is the sum over its packages."""

    profile: str
    strategy_by_work_package: dict[str, Strategy]
    loc: int
    effort_days: float
    migration_cost_jpy: int
    tco_jpy: int
    retain_tco_jpy: int
    duration_months: float


class MaintenanceCalibration(BaseModel):
    """Model estimate of a module's yearly maintenance next to the client's own figure, when the client gave one."""

    model_estimate_jpy: int
    client_reported_jpy: int | None
    applied: bool  # True when the client figure replaced the model estimate as the baseline
    gap_jpy: int | None  # model - client
    gap_pct: float | None  # gap / client x 100
    flagged: bool


class ModuleReport(BaseModel):
    module: str
    loc: int
    kloc: float
    health: ModuleHealth  # the module as a whole
    criticality: Criticality
    confidence: Literal["high", "medium", "low"]
    java_share: float | None
    maintenance_calibration: MaintenanceCalibration
    change_requests_per_year: float
    work_package_ids: list[str]
    rollups: dict[str, ModuleRollup]  # by profile name


class ProfileTotals(BaseModel):
    profile: str
    weights: Priorities
    strategy_by_work_package: dict[str, Strategy]
    strategy_mix: dict[str, int]  # strategy -> number of work packages
    total_effort_days: float
    total_migration_cost_jpy: int
    total_tco_jpy: int
    retain_tco_jpy: int
    tco_savings_vs_retain_jpy: int
    npv_vs_retain_jpy: int
    total_duration_months: float  # sum over packages: one shared programme team works them in sequence
    budget_ceiling_jpy: int
    within_budget: bool  # total migration cost <= the client's budget ceiling
    close_calls: list[str]  # work package ids


class KpiReconciliation(BaseModel):
    """The scenario's whole-ERP money KPIs next to the model, restated for the same (analysed) scope."""

    objective: str
    unit: str
    scope: str
    kpi_current: float  # as stated by the client (whole ERP)
    analysed_scope_share: float
    kpi_current_in_analysed_scope: float  # kpi_current x share
    model_baseline: float | None  # the model's baseline for the analysed scope, in the same unit (None if not modelled)
    gap: float | None  # model - scope-adjusted KPI
    gap_pct: float | None
    flagged: bool


class OutdatedDependencies(BaseModel):
    """Estate-level finding: outdated dependencies cannot be attributed to a module without its own build file."""

    declared: int
    checked: int
    unchecked: int
    outdated: int
    outdated_coordinates: list[str]


class RecommendationMeta(BaseModel):
    schema_version: str = SCHEMA_VERSION
    analysis_name: str
    analyzer: str
    selected_profile: str
    scenario_client: str
    engine: str = "rearch-engine 0.2.0"
    notes: list[str]


class Recommendation(BaseModel):
    meta: RecommendationMeta
    assumptions: dict[str, Any]  # echo of every rate/weight used, flagged ILLUSTRATIVE
    scenario: dict[str, Any]  # echo of the (fictional) client scenario
    modules: dict[str, ModuleReport]
    work_packages: dict[str, WorkPackageReport]
    hotspots: list[Hotspot]
    estate: dict[str, ProfileTotals]  # by profile name
    estate_findings: OutdatedDependencies
    kpi_reconciliation: list[KpiReconciliation]
