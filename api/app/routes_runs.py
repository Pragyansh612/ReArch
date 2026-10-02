"""Scenario versions, recommendation, roadmap, sensitivity, what-if, explain, presets and assumptions."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import select

from api.app.assumptions import EDITABLE, LABEL, PRESET_DESCRIPTIONS
from api.app.baseconfig import (
    base_engine_config,
    base_scenario,
    engine_dump,
    roadmap_dump,
)
from api.app.db import Run, unpack
from api.app.errors import ApiError, ErrorResponse, not_found
from api.app.explain import explain
from api.app.routes_analyses import svc_of
from api.app.runs import CLIENT_PROFILE, RunService
from api.app.scenario_state import (
    ScenarioEdit,
    ScenarioState,
    changed_fields,
    effective_configs,
    merge,
)
from api.app.whatif import Diff, Summary, diff, summarize
from engine.config import Priorities
from engine.recommend import recommend
from engine.roadmap.build import build_roadmap
from engine.roadmap.schema import Roadmap
from engine.schema import Recommendation

router = APIRouter(tags=["scenario and results"], responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})


class RunInfo(BaseModel):
    run_id: str
    analysis_id: str
    scenario_version: int
    input_hash: str
    cache_hit: bool
    recompute_ms: float
    sensitivity: Literal["ready", "pending"]  # flip points and breakevens are computed in the background (~4 s on OFBiz)
    profile: str
    number_id_prefix: str  # a number's id is this prefix + the JSON pointer (without its leading '/') of the number inside the document


class VersionRow(BaseModel):
    version: int
    created_at: str
    note: str


class ScenarioResponse(BaseModel):
    analysis_id: str
    version: int
    versions: list[VersionRow]
    state: ScenarioState
    illustrative: str = LABEL


class ScenarioPutResponse(BaseModel):
    created: bool  # False when the edit changed nothing and no version was added
    changed_fields: list[str]
    scenario: ScenarioResponse
    run: RunInfo


class RecommendationResponse(BaseModel):
    run: RunInfo
    recommendation: Recommendation


class RoadmapResponse(BaseModel):
    run: RunInfo
    roadmap: Roadmap


class SensitivityResponse(BaseModel):
    run: RunInfo
    packages: dict[str, dict[str, Any]]


class WhatIfResponse(BaseModel):
    profile: str
    scenario_changes: list[str]
    current: Summary
    whatif: Summary
    diff: Diff
    cache_hit: bool
    recompute_ms: float
    persisted: bool = False


class PresetRow(BaseModel):
    name: str
    description: str
    weights: Priorities
    illustrative: str = LABEL


class AssumptionRow(BaseModel):
    key: str
    label: str
    unit: str
    description: str
    group: str
    default: float | None
    current: float | None
    minimum: float
    maximum: float
    nullable: bool
    illustrative: str = LABEL


class AssumptionsResponse(BaseModel):
    illustrative: str = LABEL
    note: str = "Only these assumptions are editable (PUT /analyses/{id}/scenario, field 'assumptions'); the model's formulas are fixed."
    items: list[AssumptionRow]


def _info(svc: RunService, s: Any, run: Run, version: int, profile: str, cache_hit: bool, ms: float, doc: str = "rec") -> RunInfo:
    prefix = f"{run.id}:rec:/" if doc == "rec" else f"{run.id}:roadmap.{profile}:/"
    return RunInfo(run_id=run.id, analysis_id=run.analysis_id, scenario_version=version, input_hash=run.input_hash, cache_hit=cache_hit,
                   recompute_ms=ms, sensitivity="ready" if svc.sensitivity_ready(s, run.id) else "pending", profile=profile, number_id_prefix=prefix)


def _scenario_response(svc: RunService, s: Any, analysis_id: str, version: int | None) -> ScenarioResponse:
    rows = svc.versions(s, analysis_id)
    if not rows:
        raise not_found(f"scenario for analysis '{analysis_id}'")
    chosen = next((r for r in rows if r.version == version), None) if version is not None else rows[-1]
    if chosen is None:
        raise not_found(f"scenario version {version}")
    return ScenarioResponse(analysis_id=analysis_id, version=chosen.version, state=svc.state_of(chosen),
                            versions=[VersionRow(version=r.version, created_at=r.created_at.isoformat(), note=r.note) for r in rows])


def _resolve_version(svc: RunService, s: Any, analysis_id: str, version: int | None) -> tuple[Any, int]:
    svc.ready_analysis(s, analysis_id)
    rows = svc.versions(s, analysis_id)
    chosen = next((r for r in rows if r.version == version), None) if version is not None else (rows[-1] if rows else None)
    if chosen is None:
        raise not_found(f"scenario version {version}" if version is not None else f"scenario for analysis '{analysis_id}'")
    return svc.resolve(s, analysis_id, svc.state_of(chosen)), chosen.version


@router.get("/analyses/{analysis_id}/scenario", response_model=ScenarioResponse)
def get_scenario(analysis_id: str, request: Request, version: int | None = None) -> ScenarioResponse:
    svc = svc_of(request)
    with svc.session() as s:
        svc.ready_analysis(s, analysis_id)
        return _scenario_response(svc, s, analysis_id, version)


@router.put("/analyses/{analysis_id}/scenario", response_model=ScenarioPutResponse)
def put_scenario(analysis_id: str, edit: ScenarioEdit, request: Request) -> ScenarioPutResponse:
    """Merge the edit into the current scenario. If anything changed, a new version is created and the results are recomputed
    synchronously (no re-analysis, tens of milliseconds); the slow sensitivity search then runs in the background."""
    svc = svc_of(request)
    started = time.perf_counter()
    with svc.session() as s:
        before = svc.state_of(svc.current_version(s, analysis_id)) if svc.versions(s, analysis_id) else None
        version, created = svc.update_scenario(s, analysis_id, edit, note="edited through the API")
        resolved = svc.resolve(s, analysis_id, svc.state_of(version))
        response = ScenarioPutResponse(
            created=created, changed_fields=changed_fields(before, svc.state_of(version)) if before and created else [],
            scenario=_scenario_response(svc, s, analysis_id, version.version),
            run=_info(svc, s, resolved.run, version.version, CLIENT_PROFILE, resolved.cache_hit, round((time.perf_counter() - started) * 1000, 2)))
        if svc.settings.precompute_sensitivity and not svc.sensitivity_ready(s, resolved.run.id):
            svc.schedule_sensitivity(analysis_id, resolved.run.id)
    return response


def _trim(doc: dict[str, Any], profile: str) -> dict[str, Any]:
    """Keep one profile's choices and rollups. Pointers of the kept numbers are unchanged, so number ids stay valid."""
    out = dict(doc)
    out["meta"] = {**doc["meta"], "selected_profile": profile}
    out["work_packages"] = {k: {**w, "choices": {profile: w["choices"][profile]}} for k, w in doc["work_packages"].items()}
    out["modules"] = {k: {**m, "rollups": {profile: m["rollups"][profile]}} for k, m in doc["modules"].items()}
    return out


@router.get("/analyses/{analysis_id}/recommendation", response_model=RecommendationResponse)
def get_recommendation(analysis_id: str, request: Request, profile: str | None = Query(None, description="a preset or client_scenario"),
                       version: int | None = None) -> JSONResponse:
    svc = svc_of(request)
    with svc.session() as s:
        resolved, v = _resolve_version(svc, s, analysis_id, version)
        doc = svc.recommendation_doc(s, resolved.run)
        profile = profile or CLIENT_PROFILE
        svc.profile_known(doc, profile)
        info = _info(svc, s, resolved.run, v, profile, resolved.cache_hit, resolved.recompute_ms)
    return JSONResponse({"run": info.model_dump(), "recommendation": _trim(doc, profile)})


@router.get("/analyses/{analysis_id}/roadmap", response_model=RoadmapResponse)
def get_roadmap(analysis_id: str, request: Request, profile: str | None = None, version: int | None = None) -> JSONResponse:
    svc = svc_of(request)
    with svc.session() as s:
        resolved, v = _resolve_version(svc, s, analysis_id, version)
        profile = profile or CLIENT_PROFILE
        doc = svc.roadmap_doc(s, resolved.run, profile)
        info = _info(svc, s, resolved.run, v, profile, resolved.cache_hit, resolved.recompute_ms, doc="roadmap")
    return JSONResponse({"run": info.model_dump(), "roadmap": doc})


@router.get("/analyses/{analysis_id}/sensitivity", response_model=SensitivityResponse)
def get_sensitivity(analysis_id: str, request: Request) -> SensitivityResponse:
    """Flip points and breakevens per package (the run's selected profile). Computed on first request if the background job has not."""
    svc = svc_of(request)
    with svc.session() as s:
        resolved, v = _resolve_version(svc, s, analysis_id, None)
        run_id = resolved.run.id
    svc.compute_sensitivity(run_id)
    with svc.session() as s:
        run = s.get(Run, run_id)
        assert run is not None
        art = svc.artifact(s, run_id, "sensitivity")
        assert art is not None
        return SensitivityResponse(run=_info(svc, s, run, v, CLIENT_PROFILE, resolved.cache_hit, resolved.recompute_ms), packages=unpack(art.content))


@router.post("/analyses/{analysis_id}/whatif", response_model=WhatIfResponse)
def whatif(analysis_id: str, edit: ScenarioEdit, request: Request) -> WhatIfResponse:
    """Compute a partial scenario without persisting anything, and diff it against the current scenario."""
    svc = svc_of(request)
    started = time.perf_counter()
    with svc.session() as s:
        row, result = svc.ready_analysis(s, analysis_id)
        current = svc.current_run(s, analysis_id)
        new_state = merge(current.state, edit)
        svc.validate(new_state, result)
        scenario, cfg, rcfg, digest = svc.inputs(row, result, new_state)
        existing = s.exec(select(Run).where(Run.input_hash == digest)).first()
        rec_doc = svc.recommendation_doc(s, existing) if existing else recommend(result, cfg=cfg, scenario=scenario, sensitivity=False).model_dump(mode="json")
        profile = edit.profile or CLIENT_PROFILE
        svc.profile_known(rec_doc, profile)
        new_road = (svc.roadmap_doc(s, existing, profile, persist=False) if existing else
                    build_roadmap(Recommendation.model_validate(rec_doc), result, scenario, rcfg, profile).model_dump(mode="json"))
        cur_rec = svc.recommendation_doc(s, current.run)
        cur_road = svc.roadmap_doc(s, current.run, profile, persist=False)
        names = {k: w["name"] for k, w in rec_doc["work_packages"].items()}
        before, after = summarize(cur_rec, cur_road, profile), summarize(rec_doc, new_road, profile)
        return WhatIfResponse(profile=profile, scenario_changes=changed_fields(current.state, new_state), current=before, whatif=after,
                              diff=diff(before, after, names), cache_hit=existing is not None,
                              recompute_ms=round((time.perf_counter() - started) * 1000, 2))


@router.get("/explain/{number_id:path}")
def get_explain(number_id: str, request: Request) -> dict[str, Any]:
    """The formula, inputs, assumptions and contribution behind any number in a run or analysis response.
    A number id is `<run id>:rec:<json pointer>`, `<run id>:roadmap.<profile>:<json pointer>` or `<analysis id>:analysis:<json pointer>`;
    the responses carry `number_id_prefix` so the id of any number is prefix + the pointer of the number inside the document."""
    svc = svc_of(request)
    parts = number_id.split(":", 2)
    if len(parts) != 3:
        raise ApiError(422, "bad_number_id", "a number id looks like '<run>:<doc>:<json pointer>'")
    owner, doc_name, _ = parts
    base = doc_name.split(".", 1)[0]
    with svc.session() as s:
        if base == "analysis":
            _, result = svc.ready_analysis(s, owner)
            return explain(number_id, {"analysis": svc.analysis_doc(owner, result)}, None)
        run = s.get(Run, owner)
        if run is None:
            raise not_found(f"run '{owner}'")
        rec_doc = svc.recommendation_doc(s, run)
        if base == "rec":
            return explain(number_id, {"rec": rec_doc}, rec_doc)
        if base == "roadmap" and "." in doc_name:
            return explain(number_id, {doc_name: svc.roadmap_doc(s, run, doc_name.split(".", 1)[1])}, rec_doc)
    raise ApiError(422, "bad_number_id", f"unknown document '{doc_name}'")


@router.get("/presets", response_model=list[PresetRow])
def presets() -> list[PresetRow]:
    cfg = base_engine_config()
    rows = [PresetRow(name=n, description=PRESET_DESCRIPTIONS.get(n, ""), weights=w) for n, w in cfg.priorities.presets.items()]
    return rows + [PresetRow(name=CLIENT_PROFILE, description=PRESET_DESCRIPTIONS[CLIENT_PROFILE], weights=base_scenario().priorities)]


@router.get("/assumptions", response_model=AssumptionsResponse)
def assumptions(request: Request, analysis_id: str | None = None) -> AssumptionsResponse:
    base_engine, base_road = engine_dump(), roadmap_dump()
    current: dict[str, float | None] = {}
    if analysis_id:
        svc = svc_of(request)
        with svc.session() as s:
            svc.ready_analysis(s, analysis_id)
            eng, road = effective_configs(svc.state_of(svc.current_version(s, analysis_id)))
            current_engine, current_road = eng.model_dump(), road.model_dump()
        for k, e in EDITABLE.items():
            current[k] = _dig(current_engine if e.scope == "engine" else current_road, e.path)
    rows = [AssumptionRow(key=k, label=e.label, unit=e.unit, description=e.description, group=e.group,
                          default=_dig(base_engine if e.scope == "engine" else base_road, e.path),
                          current=current.get(k, _dig(base_engine if e.scope == "engine" else base_road, e.path)),
                          minimum=e.minimum, maximum=e.maximum, nullable=e.nullable) for k, e in EDITABLE.items()]
    return AssumptionsResponse(items=rows)


def _dig(doc: dict[str, Any], path: tuple[str, ...]) -> float | None:
    cur: Any = doc
    for p in path:
        cur = cur[p]
    return None if cur is None else float(cur)
