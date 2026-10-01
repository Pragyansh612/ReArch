"""The (fictional) client scenario: problem, KPIs, constraints, priorities and criticality overrides."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from engine.config import DEFAULT_SCENARIO, EngineConfig, Override, Priorities


class Objective(BaseModel):
    id: str
    label: str
    unit: str
    current: float
    target: float
    weight: float
    scope: str = "whole_erp"
    illustrative: bool = True


class Constraints(BaseModel):
    planning_horizon_years: int
    budget_ceiling_jpy: int
    max_cutover_downtime_hours: dict[str, float] = {}


class ClientScenario(BaseModel):
    client: dict[str, object]
    problem: dict[str, object]
    objectives: list[Objective]
    constraints: Constraints
    priorities: Priorities
    analysed_scope_share: float = 1.0
    change_requests_per_year: dict[str, float] = {}
    client_reported_maintenance_jpy: dict[str, int | None] = {}
    criticality_overrides: dict[str, list[Override]] = {}

    @model_validator(mode="after")
    def _weights(self) -> ClientScenario:
        total = sum(o.weight for o in self.objectives)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"objective weights must sum to 1, got {total}")
        if not 0.0 < self.analysed_scope_share <= 1.0:
            raise ValueError("analysed_scope_share must be in (0, 1]")
        if self.constraints.planning_horizon_years < 1:
            raise ValueError("planning horizon must be at least one year")
        return self

    def overrides_for(self, analysis_name: str) -> dict[str, Override]:
        return {o.module: o for o in self.criticality_overrides.get(analysis_name, [])}

    def change_requests(self, module: str) -> float:
        table = self.change_requests_per_year
        return float(table.get(module, table.get("default", 0.0)))

    def objective_weights(self) -> dict[str, float]:
        return {o.id: o.weight for o in self.objectives}


def load_scenario(path: Path = DEFAULT_SCENARIO) -> ClientScenario:
    return ClientScenario(**yaml.safe_load(path.read_text(encoding="utf-8")))


def check_consistency(scenario: ClientScenario, cfg: EngineConfig) -> None:
    """Every objective needs an effect entry for every strategy, and vice versa."""
    ids = {o.id for o in scenario.objectives}
    for strategy, effects in cfg.long_term_value.objective_effect.items():
        if set(effects) != ids:
            raise ValueError(f"objective_effect[{strategy}] must cover exactly the scenario objectives {sorted(ids)}")
    missing = set(cfg.strategies) - set(cfg.long_term_value.objective_effect)
    if missing:
        raise ValueError(f"objective_effect is missing strategies {sorted(missing)}")
