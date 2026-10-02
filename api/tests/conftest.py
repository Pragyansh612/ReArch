from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analyzer.analyze import analyze
from api.app.db import Analysis
from api.app.main import create_app
from api.app.settings import ROOT, Settings

FIXTURE = ROOT / "fixtures" / "legacy-sample"


@pytest.fixture(scope="session")
def fixture_json() -> str:
    return analyze(FIXTURE, name="legacy-sample").model_dump_json()


def make_settings(tmp: Path, **kw: object) -> Settings:
    base = {"data_dir": tmp / "data", "demo_dir": tmp / "demo", "path_roots": [ROOT / "fixtures"], "precompute_sensitivity": False, "sensitivity_executor": "inline", "sensitivity_debounce_s": 0.0}
    return Settings(**{**base, **kw})  # type: ignore[arg-type]


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return create_app(make_settings(tmp_path))


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def register(app: FastAPI, fixture_json: str) -> Callable[..., str]:
    """Register the (pre-analysed) fixture directly, without the clone/analyse subprocess."""

    def _register(analysis_id: str = "demo") -> str:
        svc = app.state.svc
        with svc.session() as s:
            row = Analysis(id=analysis_id, name="legacy-sample", source="user", status="done", repo="fixtures/legacy-sample")
            s.add(row)
            s.commit()
            svc.store_analysis(s, row, fixture_json)
        return analysis_id

    return _register


@pytest.fixture
def aid(register: Callable[..., str]) -> str:
    return register()


def write_demo(demo_dir: Path, fixture_json: str) -> None:
    demo_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(demo_dir / "legacy-sample.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(fixture_json)
    (demo_dir / "manifest.json").write_text(json.dumps({"legacy-sample": {"repo": "fixtures/legacy-sample", "scope": []}}))
