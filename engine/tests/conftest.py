from __future__ import annotations

from pathlib import Path

import pytest

from analyzer.analyze import analyze
from analyzer.schema import AnalysisResult
from engine.config import EngineConfig, load_engine_config
from engine.recommend import recommend
from engine.schema import Recommendation

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "legacy-sample"


@pytest.fixture(scope="session")
def analysis() -> AnalysisResult:
    return analyze(FIXTURE, name="legacy-sample")


@pytest.fixture(scope="session")
def cfg() -> EngineConfig:
    return load_engine_config()


@pytest.fixture(scope="session")
def rec(analysis: AnalysisResult, cfg: EngineConfig) -> Recommendation:
    # overrides={} so the committed criticality_overrides.yaml can never influence these tests
    return recommend(analysis, cfg=cfg, overrides={})
