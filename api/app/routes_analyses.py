"""Analyses: create (background job), status, summary, and the read-only views (modules, packages, classes, graph)."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from analyzer.schema import AnalysisResult, Finding
from api.app import queries
from api.app.db import Analysis, now
from api.app.errors import ApiError, ErrorResponse
from api.app.jobs import create_job, run_job
from api.app.runs import RunService

router = APIRouter(tags=["analyses"], responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})


def svc_of(request: Request) -> RunService:
    svc: RunService = request.app.state.svc
    return svc


class AnalysisCreate(BaseModel):
    repo: str = Field(description="an https git URL, or an absolute server path under a configured root")
    scope: list[str] = Field(default=[], description="directories relative to the repo to analyse; empty = the whole repo")
    name: str | None = Field(default=None, description="letters, digits, '.', '_' and '-'; default derived from the repo")


class AnalysisStatus(BaseModel):
    id: str
    name: str
    status: Literal["queued", "cloning", "analyzing", "done", "failed"]
    message: str
    source: str
    elapsed_seconds: float
    classes: int
    loc: int


class AnalysisListItem(BaseModel):
    id: str
    name: str
    source: str
    status: str
    classes: int
    loc: int
    created_at: str


class CoverageRow(BaseModel):
    module: str
    confidence: str
    java_share: float | None
    java_defs: int
    implemented_defs: int
    entity_auto_defs: int
    groovy_logic_files: int
    service_defs_by_engine: dict[str, int]


class FindingsSummary(BaseModel):
    by_kind: dict[str, int]
    broken_references: list[Finding]
    module_cycles: list[list[str]]
    class_cycle_count: int
    god_classes: dict[str, int]
    dependencies: dict[str, int]
    parse_errors: list[str]


class AnalysisSummary(BaseModel):
    id: str
    name: str
    source: str
    repo: str
    scope: list[str]
    created_at: str
    totals: dict[str, int]
    coverage: list[CoverageRow]
    findings: FindingsSummary
    unanalyzed: dict[str, Any]
    scenario_version: int
    run_id: str
    number_id_prefix: str


def _status(row: Analysis) -> AnalysisStatus:
    end = row.finished_at or now()
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=end.tzinfo)
    return AnalysisStatus(id=row.id, name=row.name, status=row.status, message=row.message, source=row.source,  # type: ignore[arg-type]
                          elapsed_seconds=round(max(0.0, (end - created).total_seconds()), 2), classes=row.classes, loc=row.loc)


@router.post("/analyses", status_code=202, response_model=AnalysisStatus)
def create_analysis(body: AnalysisCreate, request: Request, background: BackgroundTasks) -> AnalysisStatus:
    svc = svc_of(request)
    if svc.settings.demo_mode:
        raise ApiError(403, "demo_mode", "this server runs in demo mode: analysing new repositories is disabled; preloaded analyses are available")
    row = create_job(svc, body.repo, body.scope, body.name, svc.settings)
    background.add_task(run_job, svc, row.id)
    return _status(row)


@router.get("/analyses/{analysis_id}/status", response_model=AnalysisStatus)
def analysis_status(analysis_id: str, request: Request) -> AnalysisStatus:
    svc = svc_of(request)
    with svc.session() as s:
        return _status(svc.get_analysis(s, analysis_id))


@router.get("/analyses", response_model=list[AnalysisListItem])
def list_analyses(request: Request) -> list[AnalysisListItem]:
    svc = svc_of(request)
    from sqlmodel import select

    with svc.session() as s:
        rows = list(s.exec(select(Analysis).order_by(Analysis.created_at)))  # type: ignore[arg-type]
    return [AnalysisListItem(id=r.id, name=r.name, source=r.source, status=r.status, classes=r.classes, loc=r.loc,
                             created_at=r.created_at.isoformat()) for r in rows]


def _summary(row: Analysis, result: AnalysisResult, version: int, run_id: str) -> AnalysisSummary:
    kinds: dict[str, int] = {}
    for f in result.findings:
        kinds[f.kind] = kinds.get(f.kind, 0) + 1
    deps = result.dependencies
    u = result.unanalyzed_files
    return AnalysisSummary(
        id=row.id, name=row.name, source=row.source, repo=row.repo, scope=json.loads(row.scope), created_at=row.created_at.isoformat(),
        totals=result.totals.model_dump(),
        coverage=[CoverageRow(module=n, confidence=m.coverage.confidence, java_share=m.coverage.java_share, java_defs=m.coverage.java_defs,
                              implemented_defs=m.coverage.implemented_defs, entity_auto_defs=m.coverage.entity_auto_defs,
                              groovy_logic_files=m.coverage.groovy_logic_files, service_defs_by_engine=m.coverage.service_defs_by_engine)
                  for n, m in result.modules.items()],
        findings=FindingsSummary(
            by_kind=dict(sorted(kinds.items())), broken_references=[f for f in result.findings if f.kind == "broken_reference"],
            module_cycles=result.cycles.module_cycles, class_cycle_count=len(result.cycles.class_cycles),
            god_classes={"large": sum(c.size_tier == "large" for c in result.classes.values()),
                         "extreme": sum(c.size_tier == "extreme" for c in result.classes.values())},
            dependencies={"declared": len(deps), "checked": sum(d.checked for d in deps), "outdated": sum(bool(d.outdated) for d in deps)},
            parse_errors=result.meta.parse_errors),
        unanalyzed={"groovy_files": u.groovy_count, "service_engine_counts": u.service_engine_counts, "controller_event_counts": u.controller_event_counts,
                    "testdef_files": len(u.testdef_files)},
        scenario_version=version, run_id=run_id, number_id_prefix=f"{row.id}:analysis:/")


@router.get("/analyses/{analysis_id}", response_model=AnalysisSummary)
def analysis_summary(analysis_id: str, request: Request) -> AnalysisSummary:
    svc = svc_of(request)
    with svc.session() as s:
        row, result = svc.ready_analysis(s, analysis_id)
        version = svc.current_version(s, analysis_id)
        return _summary(row, result, version.version, svc.current_run(s, analysis_id).run.id)


@router.get("/analyses/{analysis_id}/modules", response_model=queries.ModulesPage)
def modules(analysis_id: str, request: Request, min_loc: int = 0, confidence: Literal["high", "medium", "low"] | None = None,
            has_tests: bool | None = None, sort_by: str = "loc", descending: bool = True, limit: int = Query(50, ge=1, le=500),
            offset: int = Query(0, ge=0)) -> queries.ModulesPage:
    svc = svc_of(request)
    with svc.session() as s:
        _, result = svc.ready_analysis(s, analysis_id)
    return queries.modules_page(result, svc.prepared(analysis_id, result), min_loc=min_loc, confidence=confidence, has_tests=has_tests,
                                sort_by=sort_by, descending=descending, limit=limit, offset=offset)


@router.get("/analyses/{analysis_id}/packages", response_model=queries.PackagesPage)
def packages(analysis_id: str, request: Request, module: str | None = None, kind: Literal["cycle", "god_class_cluster", "remainder"] | None = None,
             sort_by: str = "loc", descending: bool = True, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> queries.PackagesPage:
    svc = svc_of(request)
    with svc.session() as s:
        _, result = svc.ready_analysis(s, analysis_id)
    return queries.packages_page(svc.prepared(analysis_id, result), module=module, kind=kind, sort_by=sort_by, descending=descending,
                                 limit=limit, offset=offset)


@router.get("/analyses/{analysis_id}/classes", response_model=queries.ClassesPage)
def classes(analysis_id: str, request: Request, q: str | None = None, module: str | None = None, package: str | None = None,
            tier: Literal["none", "large", "extreme"] | None = None, used: bool | None = None, min_loc: int = 0, sort_by: str = "hotspot",
            descending: bool = True, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> queries.ClassesPage:
    svc = svc_of(request)
    with svc.session() as s:
        _, result = svc.ready_analysis(s, analysis_id)
    return queries.classes_page(result, svc.prepared(analysis_id, result), q=q, module=module, package=package, tier=tier, used=used,
                                min_loc=min_loc, sort_by=sort_by, descending=descending, limit=limit, offset=offset)


@router.get("/analyses/{analysis_id}/classes/{name:path}", response_model=queries.ClassDetail)
def class_detail(analysis_id: str, name: str, request: Request) -> queries.ClassDetail:
    svc = svc_of(request)
    with svc.session() as s:
        _, result = svc.ready_analysis(s, analysis_id)
    return queries.class_detail(result, svc.prepared(analysis_id, result), analysis_id, name)


@router.get("/analyses/{analysis_id}/graph", response_model=queries.GraphResponse)
def graph(analysis_id: str, request: Request, level: Literal["module", "package", "class"] = "module", limit: int = Query(80, ge=1, le=500),
          module: str | None = None, package: str | None = None) -> JSONResponse | queries.GraphResponse:
    svc = svc_of(request)
    with svc.session() as s:
        _, result = svc.ready_analysis(s, analysis_id)
    return queries.graph(result, svc.prepared(analysis_id, result), level, limit, module, package)
