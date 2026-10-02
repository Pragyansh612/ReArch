"""Versioned scenario state: what a client may edit, with validation, merging and the effective configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from api.app.assumptions import EDITABLE
from api.app.baseconfig import base_scenario, engine_dump, roadmap_dump
from api.app.errors import ApiError
from engine.config import EngineConfig, Override, Priorities
from engine.roadmap.config import RoadmapConfig
from engine.scenario import ClientScenario, Constraints


def _check_priorities(p: Priorities) -> None:
    if any(w < 0 or w > 1 for w in p.model_dump().values()):
        raise ValueError("each priority weight must be between 0 and 1")


class OverrideIn(BaseModel):
    criticality: int = Field(ge=1, le=3)
    reason: str = Field(min_length=10, description="A written reason is required (shown next to the value)")


class ScenarioState(BaseModel):
    """A complete, resolved scenario version."""

    priorities: Priorities
    objective_weights: dict[str, float]
    budget_ceiling_jpy: int = Field(ge=1_000_000, le=10**12)
    planning_horizon_years: int = Field(ge=1, le=10)
    max_cutover_downtime_hours: dict[str, float]
    criticality_overrides: dict[str, OverrideIn]
    client_reported_maintenance_jpy: dict[str, int | None]
    change_requests_per_year: dict[str, float]
    analysed_scope_share: float = Field(gt=0.0, le=1.0)
    assumptions: dict[str, float | None]  # dotted keys from api.app.assumptions.EDITABLE

    @field_validator("priorities")
    @classmethod
    def _priority_bounds(cls, v: Priorities) -> Priorities:
        _check_priorities(v)
        return v

    @field_validator("objective_weights")
    @classmethod
    def _weights(cls, v: dict[str, float]) -> dict[str, float]:
        if any(w < 0 or w > 1 for w in v.values()) or abs(sum(v.values()) - 1.0) > 1e-6:
            raise ValueError("objective weights must each be between 0 and 1 and sum to 1")
        return v

    @field_validator("max_cutover_downtime_hours")
    @classmethod
    def _downtime(cls, v: dict[str, float]) -> dict[str, float]:
        if any(h < 0 or h > 72 for h in v.values()):
            raise ValueError("cutover downtime limits must be between 0 and 72 hours")
        return v

    @field_validator("client_reported_maintenance_jpy")
    @classmethod
    def _maintenance(cls, v: dict[str, int | None]) -> dict[str, int | None]:
        if any(x is not None and (x < 0 or x > 10**11) for x in v.values()):
            raise ValueError("client-reported maintenance must be between 0 and 100 billion JPY a year")
        return v

    @field_validator("change_requests_per_year")
    @classmethod
    def _changes(cls, v: dict[str, float]) -> dict[str, float]:
        if any(x < 0 or x > 10_000 for x in v.values()):
            raise ValueError("change requests per year must be between 0 and 10,000")
        return v

    @field_validator("assumptions")
    @classmethod
    def _assumptions(cls, v: dict[str, float | None]) -> dict[str, float | None]:
        for key, value in v.items():
            spec = EDITABLE.get(key)
            if spec is None:
                raise ValueError(f"'{key}' is not an editable assumption (see GET /assumptions)")
            if value is None:
                if not spec.nullable:
                    raise ValueError(f"'{key}' cannot be null")
            elif not spec.minimum <= value <= spec.maximum:
                raise ValueError(f"'{key}' must be between {spec.minimum:g} and {spec.maximum:g} {spec.unit}")
        return v


class ScenarioEdit(BaseModel):
    """A partial edit. Omitted fields keep their value; map fields merge by key (null removes a key)."""

    priorities: Priorities | None = None
    objective_weights: dict[str, float] | None = None
    budget_ceiling_jpy: int | None = Field(default=None, ge=1_000_000, le=10**12)
    planning_horizon_years: int | None = Field(default=None, ge=1, le=10)
    max_cutover_downtime_hours: dict[str, float | None] | None = None
    criticality_overrides: dict[str, OverrideIn | None] | None = None
    client_reported_maintenance_jpy: dict[str, int | None] | None = None
    change_requests_per_year: dict[str, float | None] | None = None
    analysed_scope_share: float | None = Field(default=None, gt=0.0, le=1.0)
    assumptions: dict[str, float | None] | None = None
    profile: str | None = Field(default=None, description="what-if only: the profile whose result and diff are returned")

    @field_validator("priorities")
    @classmethod
    def _priority_bounds(cls, v: Priorities | None) -> Priorities | None:
        if v is not None:
            _check_priorities(v)
        return v

    @model_validator(mode="after")
    def _not_empty(self) -> ScenarioEdit:
        if not self.model_dump(exclude_none=True, exclude={"profile"}) and not any(
                isinstance(v, dict) and v for v in (self.criticality_overrides, self.client_reported_maintenance_jpy)):
            raise ValueError("the edit changes nothing: give at least one field")
        return self


def initial_state(analysis_name: str, modules: set[str] | None = None, scenario: ClientScenario | None = None) -> ScenarioState:
    """The scenario file's values for this analysis. Entries for modules the analysis does not have are dropped (the file is
    written for one codebase; another analysis only keeps what applies to it)."""
    sc = scenario or base_scenario()

    def keep(module: str) -> bool:
        return modules is None or module in modules

    return ScenarioState(
        priorities=sc.priorities, objective_weights=sc.objective_weights(), budget_ceiling_jpy=sc.constraints.budget_ceiling_jpy,
        planning_horizon_years=sc.constraints.planning_horizon_years,
        max_cutover_downtime_hours={m: h for m, h in sc.constraints.max_cutover_downtime_hours.items() if keep(m)},
        criticality_overrides={m: OverrideIn(criticality=o.criticality, reason=o.reason) for m, o in sc.overrides_for(analysis_name).items() if keep(m)},
        client_reported_maintenance_jpy={m: v for m, v in sc.client_reported_maintenance_jpy.items() if keep(m)},
        change_requests_per_year={m: v for m, v in sc.change_requests_per_year.items() if m == "default" or keep(m)},
        analysed_scope_share=sc.analysed_scope_share, assumptions={})


def merge(state: ScenarioState, edit: ScenarioEdit) -> ScenarioState:
    data: dict[str, Any] = state.model_dump()
    for field in ("priorities", "objective_weights", "budget_ceiling_jpy", "planning_horizon_years", "analysed_scope_share"):
        value = getattr(edit, field)
        if value is not None:
            data[field] = value.model_dump() if isinstance(value, BaseModel) else value
    for field in ("max_cutover_downtime_hours", "criticality_overrides", "client_reported_maintenance_jpy", "change_requests_per_year",
                  "assumptions"):
        patch = getattr(edit, field)
        if patch is None:
            continue
        for key, value in patch.items():
            if value is None and field != "assumptions":
                data[field].pop(key, None)
            else:
                data[field][key] = value.model_dump() if isinstance(value, BaseModel) else value
    try:
        return ScenarioState.model_validate(data)
    except ValidationError as exc:
        raise ApiError(422, "validation_error", "the scenario is not valid",
                       [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"].removeprefix("Value error, ")} for e in exc.errors()]) from exc


def check_against_analysis(state: ScenarioState, modules: set[str], objective_ids: set[str]) -> list[dict[str, str]]:
    """Problems that need the analysis to detect (unknown module names, wrong objective ids)."""
    problems: list[dict[str, str]] = []
    for field in ("criticality_overrides", "client_reported_maintenance_jpy", "max_cutover_downtime_hours"):
        for module in getattr(state, field):
            if module not in modules:
                problems.append({"field": f"{field}.{module}", "message": f"unknown module '{module}'; known: {sorted(modules)}"})
    for module in state.change_requests_per_year:
        if module != "default" and module not in modules:
            problems.append({"field": f"change_requests_per_year.{module}", "message": f"unknown module '{module}'"})
    if set(state.objective_weights) != objective_ids:
        problems.append({"field": "objective_weights", "message": f"must cover exactly {sorted(objective_ids)}"})
    return problems


def build_scenario(state: ScenarioState, analysis_name: str) -> ClientScenario:
    base = base_scenario()
    objectives = [o.model_copy(update={"weight": state.objective_weights[o.id]}) for o in base.objectives]
    return base.model_copy(update={
        "priorities": state.priorities, "objectives": objectives,
        "constraints": Constraints(planning_horizon_years=state.planning_horizon_years, budget_ceiling_jpy=state.budget_ceiling_jpy,
                                   max_cutover_downtime_hours=state.max_cutover_downtime_hours),
        "analysed_scope_share": state.analysed_scope_share, "change_requests_per_year": state.change_requests_per_year,
        "client_reported_maintenance_jpy": state.client_reported_maintenance_jpy,
        "criticality_overrides": {analysis_name: [Override(module=m, criticality=o.criticality, reason=o.reason)
                                                  for m, o in sorted(state.criticality_overrides.items())]}})


def _apply(dump: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    for part in path[:-1]:
        dump = dump[part]
    dump[path[-1]] = value


_INT_KEYS = {k for k, e in EDITABLE.items() if e.unit in ("teams", "people") or k.endswith("yearly_budget_cap_jpy")}


def effective_configs(state: ScenarioState) -> tuple[EngineConfig, RoadmapConfig]:
    engine, roadmap = engine_dump(), roadmap_dump()
    for key, value in sorted(state.assumptions.items()):
        spec = EDITABLE[key]
        typed = None if value is None else int(value) if key in _INT_KEYS else float(value)
        _apply(engine if spec.scope == "engine" else roadmap, spec.path, typed)
    return EngineConfig.model_validate(engine), RoadmapConfig.model_validate(roadmap)


def changed_fields(old: ScenarioState, new: ScenarioState) -> list[str]:
    a, b = old.model_dump(), new.model_dump()
    out: list[str] = []
    for field in a:
        if a[field] == b[field]:
            continue
        if isinstance(a[field], dict) and isinstance(b[field], dict) and field != "priorities":
            out += [f"{field}.{k}" for k in sorted(set(a[field]) | set(b[field])) if a[field].get(k) != b[field].get(k)]
        elif field == "priorities":
            out += [f"priorities.{k}" for k in a[field] if a[field][k] != b[field][k]]
        else:
            out.append(field)
    return out
