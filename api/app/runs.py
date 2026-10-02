"""Runs: analyses, scenario versions, the recommendation for (analysis x scenario), cached by a hash of its inputs."""

from __future__ import annotations

import gzip
import hashlib
import json
import multiprocessing
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from analyzer.schema import AnalysisResult
from api.app.baseconfig import base_scenario
from api.app.db import Analysis, Run, RunArtifact, ScenarioVersion, now, pack, unpack
from api.app.errors import ApiError, not_found
from api.app.prepared import Prepared, prepare
from api.app.scenario_state import (
    ScenarioEdit,
    ScenarioState,
    build_scenario,
    check_against_analysis,
    effective_configs,
    initial_state,
    merge,
)
from api.app.sens_worker import compute_job
from api.app.settings import ENGINE_VERSION, Settings
from engine.recommend import recommend
from engine.roadmap.build import build_roadmap
from engine.schema import Recommendation

CLIENT_PROFILE = "client_scenario"


def canonical(doc: Any) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class Resolved:
    state: ScenarioState
    run: Run
    cache_hit: bool
    recompute_ms: float


class RunService:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.engine, self.settings = engine, settings
        self._analyses: dict[str, AnalysisResult] = {}
        self._prepared: dict[str, Prepared] = {}
        self._analysis_docs: dict[str, dict[str, Any]] = {}
        self._docs: OrderedDict[tuple[str, ...], dict[str, Any]] = OrderedDict()  # recent run documents; callers must not mutate
        self._lock = threading.RLock()
        self._executor: ProcessPoolExecutor | None = None
        self._inflight: dict[str, Future[dict[str, Any]]] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._latest: dict[str, str] = {}

    # --- analyses -------------------------------------------------------------------------------------------------------------
    def session(self) -> Session:
        return Session(self.engine)

    def get_analysis(self, s: Session, analysis_id: str) -> Analysis:
        row = s.get(Analysis, analysis_id)
        if row is None:
            raise not_found(f"analysis '{analysis_id}'")
        return row

    def ready_analysis(self, s: Session, analysis_id: str) -> tuple[Analysis, AnalysisResult]:
        row = self.get_analysis(s, analysis_id)
        if row.status != "done":
            raise ApiError(409, "analysis_not_ready", f"analysis '{analysis_id}' is {row.status}: {row.message}".strip())
        if analysis_id not in self._analyses:
            with gzip.open(self.settings.data_dir / row.result_file, "rt", encoding="utf-8") as fh:
                self._analyses[analysis_id] = AnalysisResult.model_validate_json(fh.read())
        return row, self._analyses[analysis_id]

    def prepared(self, analysis_id: str, result: AnalysisResult) -> Prepared:
        if analysis_id not in self._prepared:
            self._prepared[analysis_id] = prepare(result)
        return self._prepared[analysis_id]

    def analysis_doc(self, analysis_id: str, result: AnalysisResult) -> dict[str, Any]:
        if analysis_id not in self._analysis_docs:
            self._analysis_docs[analysis_id] = result.model_dump(mode="json")
        return self._analysis_docs[analysis_id]

    def store_analysis(self, s: Session, row: Analysis, result_json: str) -> None:
        """Persist an immutable analyzer output and create scenario version 1 with its first run."""
        folder = self.settings.data_dir / "analyses"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{row.id}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(result_json)
        result = AnalysisResult.model_validate_json(result_json)
        row.result_file, row.content_hash = str(path.relative_to(self.settings.data_dir)), hashlib.sha256(result_json.encode()).hexdigest()
        row.classes, row.loc, row.status, row.finished_at = result.totals.main_java_classes, result.totals.main_java_loc, "done", now()
        s.add(row)
        s.commit()
        self._analyses[row.id] = result
        state = initial_state(result.meta.name, set(result.modules))
        s.add(ScenarioVersion(analysis_id=row.id, version=1, content=pack(state.model_dump()), note="initial scenario from config/client_scenario.yaml"))
        s.commit()
        self.resolve(s, row.id, state)

    # --- scenario versions -------------------------------------------------------------------------------------------------------
    def versions(self, s: Session, analysis_id: str) -> list[ScenarioVersion]:
        return list(s.exec(select(ScenarioVersion).where(ScenarioVersion.analysis_id == analysis_id).order_by(ScenarioVersion.version)))  # type: ignore[arg-type]

    def current_version(self, s: Session, analysis_id: str) -> ScenarioVersion:
        rows = self.versions(s, analysis_id)
        if not rows:
            raise not_found(f"scenario for analysis '{analysis_id}'")
        return rows[-1]

    def state_of(self, v: ScenarioVersion) -> ScenarioState:
        return ScenarioState.model_validate(unpack(v.content))

    def validate(self, state: ScenarioState, analysis: AnalysisResult) -> None:
        problems = check_against_analysis(state, set(analysis.modules), {o.id for o in base_scenario().objectives})
        if problems:
            raise ApiError(422, "validation_error", "the scenario does not fit this analysis", problems)

    def update_scenario(self, s: Session, analysis_id: str, edit: ScenarioEdit, note: str = "") -> tuple[ScenarioVersion, bool]:
        """Apply a partial edit; add a new version only if something changed. Returns (version, created)."""
        _, analysis = self.ready_analysis(s, analysis_id)
        current = self.current_version(s, analysis_id)
        new = merge(self.state_of(current), edit)
        self.validate(new, analysis)
        if new == self.state_of(current):
            return current, False
        version = ScenarioVersion(analysis_id=analysis_id, version=current.version + 1, content=pack(new.model_dump()), note=note)
        s.add(version)
        s.commit()
        s.refresh(version)
        return version, True

    # --- runs ---------------------------------------------------------------------------------------------------------------------
    def inputs(self, analysis: Analysis, result: AnalysisResult, state: ScenarioState):  # type: ignore[no-untyped-def]
        scenario = build_scenario(state, result.meta.name)
        cfg, rcfg = effective_configs(state)
        digest = hashlib.sha256(canonical({"analysis": analysis.content_hash, "scenario": scenario.model_dump(mode="json"),
                                           "engine": cfg.model_dump(mode="json"), "roadmap": rcfg.model_dump(mode="json"),
                                           "version": ENGINE_VERSION}).encode()).hexdigest()
        return scenario, cfg, rcfg, digest

    def resolve(self, s: Session, analysis_id: str, state: ScenarioState) -> Resolved:
        """The run for these inputs: from the cache if the same inputs were computed before, else computed and stored."""
        started = time.perf_counter()
        row, result = self.ready_analysis(s, analysis_id)
        scenario, cfg, _, digest = self.inputs(row, result, state)
        existing = s.exec(select(Run).where(Run.input_hash == digest)).first()
        if existing is not None:
            return Resolved(state, existing, True, round((time.perf_counter() - started) * 1000, 2))
        rec = recommend(result, cfg=cfg, scenario=scenario, sensitivity=False)
        run = Run(id=digest[:16], analysis_id=analysis_id, input_hash=digest, recommendation=pack(rec.model_dump(mode="json")),
                  state=pack(state.model_dump()))
        s.add(run)
        s.commit()
        s.refresh(run)
        self.roadmap_doc(s, run, CLIENT_PROFILE)  # warm the default roadmap so the first read is instant
        return Resolved(state, run, False, round((time.perf_counter() - started) * 1000, 2))

    def current_run(self, s: Session, analysis_id: str) -> Resolved:
        return self.resolve(s, analysis_id, self.state_of(self.current_version(s, analysis_id)))

    # --- documents ----------------------------------------------------------------------------------------------------------------
    def artifact(self, s: Session, run_id: str, kind: str, key: str = "") -> RunArtifact | None:
        return s.exec(select(RunArtifact).where(RunArtifact.run_id == run_id, RunArtifact.kind == kind, RunArtifact.key == key)).first()

    def sensitivity_ready(self, s: Session, run_id: str) -> bool:
        return self.artifact(s, run_id, "sensitivity") is not None

    def _remember(self, key: tuple[str, ...], doc: dict[str, Any]) -> dict[str, Any]:
        self._docs[key] = doc
        self._docs.move_to_end(key)
        while len(self._docs) > 12:
            self._docs.popitem(last=False)
        return doc

    def recommendation_doc(self, s: Session, run: Run) -> dict[str, Any]:
        sens = self.artifact(s, run.id, "sensitivity")
        key = ("rec", run.id, "sens" if sens is not None else "fast")
        if key in self._docs:
            return self._docs[key]
        doc: dict[str, Any] = unpack(run.recommendation)
        if sens is not None:  # merge the slow part in once it exists
            for wid, extra in unpack(sens.content).items():
                doc["work_packages"][wid]["sensitivity"] = extra["sensitivity"]
                doc["work_packages"][wid]["breakeven"] = extra["breakeven"]
        return self._remember(key, doc)

    def roadmap_doc(self, s: Session, run: Run, profile: str, persist: bool = True) -> dict[str, Any]:
        key = ("roadmap", run.id, profile, "sens" if self.sensitivity_ready(s, run.id) else "fast")
        if key in self._docs:
            return self._docs[key]
        cached = self.artifact(s, run.id, "roadmap", profile)
        if cached is not None:
            return self._remember(key, dict(unpack(cached.content)))
        row, result = self.ready_analysis(s, run.analysis_id)
        state = ScenarioState.model_validate(unpack(run.state))
        scenario, _, rcfg, _ = self.inputs(row, result, state)
        rec = Recommendation.model_validate(self.recommendation_doc(s, run))
        if profile not in rec.estate:
            raise ApiError(422, "unknown_profile", f"unknown profile '{profile}'; known: {sorted(rec.estate)}")
        doc = build_roadmap(rec, result, scenario, rcfg, profile).model_dump(mode="json")
        if persist:
            s.add(RunArtifact(run_id=run.id, kind="roadmap", key=profile, content=pack(doc)))
            s.commit()
            self._remember(key, doc)
        return doc

    # --- the slow part: flip points and breakevens ----------------------------------------------------------------------------
    def _pool(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        return self._executor

    def schedule_sensitivity(self, analysis_id: str, run_id: str) -> None:
        """Non-blocking and debounced: only the latest run of an analysis is computed, once edits have gone quiet."""
        with self._lock:
            self._latest[analysis_id] = run_id
            timer = self._timers.pop(analysis_id, None)
            if timer is not None:
                timer.cancel()
            delay = self.settings.sensitivity_debounce_s
            timer = threading.Timer(delay, self._fire, args=(analysis_id, run_id))
            timer.daemon = True
            self._timers[analysis_id] = timer
            timer.start()

    def _fire(self, analysis_id: str, run_id: str) -> None:
        with self._lock:
            if self._latest.get(analysis_id) != run_id:
                return  # superseded by a newer edit
        try:
            self.compute_sensitivity(run_id)
        except Exception:  # noqa: BLE001  background work must never crash the server; the run just stays "pending"
            return

    def compute_sensitivity(self, run_id: str) -> None:
        """Compute (or wait for) a run's sensitivity and store it. Blocking, but the work happens in another process."""
        with self.session() as s:
            run = s.get(Run, run_id)
            if run is None or self.artifact(s, run_id, "sensitivity") is not None:
                return
            analysis_file, state = str(self.settings.data_dir / self.get_analysis(s, run.analysis_id).result_file), unpack(run.state)
        with self._lock:
            future = self._inflight.get(run_id)
            if future is None:
                if self.settings.sensitivity_executor == "inline":
                    future = Future()
                    future.set_result(compute_job(analysis_file, state))
                else:
                    future = self._pool().submit(compute_job, analysis_file, state)
                self._inflight[run_id] = future
        extra = future.result()
        with self._lock:
            if self._inflight.pop(run_id, None) is None:
                return  # another caller already stored it
        with self.session() as s:
            if self.artifact(s, run_id, "sensitivity") is None:
                s.add(RunArtifact(run_id=run_id, kind="sensitivity", key="", content=pack(extra)))
                for stale in s.exec(select(RunArtifact).where(RunArtifact.run_id == run_id, RunArtifact.kind == "roadmap")).all():
                    s.delete(stale)  # roadmaps built before the breakevens existed lack their headline
                s.commit()
        self._docs.clear()

    def shutdown(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def profile_known(self, doc: dict[str, Any], profile: str) -> None:
        if profile not in doc["estate"]:
            raise ApiError(422, "unknown_profile", f"unknown profile '{profile}'; known: {sorted(doc['estate'])}")


def data_path(settings: Settings, rel: str) -> Path:
    return settings.data_dir / rel
