from __future__ import annotations

from pathlib import Path

import pytest

from analyzer.analyze import analyze
from analyzer.schema import AnalysisResult
from engine.config import EngineConfig, load_engine_config
from engine.recommend import recommend
from engine.scenario import ClientScenario, load_scenario
from engine.schema import Recommendation

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "legacy-sample"


@pytest.fixture(scope="session")
def analysis() -> AnalysisResult:
    return analyze(FIXTURE, name="legacy-sample")


@pytest.fixture(scope="session")
def cfg() -> EngineConfig:
    return load_engine_config()


@pytest.fixture(scope="session")
def scenario() -> ClientScenario:
    return load_scenario()


@pytest.fixture(scope="session")
def rec(analysis: AnalysisResult, cfg: EngineConfig, scenario: ClientScenario) -> Recommendation:
    return recommend(analysis, cfg=cfg, scenario=scenario)  # includes the sensitivity search


@pytest.fixture(scope="session")
def rcfg():  # type: ignore[no-untyped-def]
    from engine.roadmap.config import load_roadmap_config

    return load_roadmap_config()


@pytest.fixture(scope="session")
def tight_scenario(scenario: ClientScenario) -> ClientScenario:
    """A budget (JPY 20M) below the fixture's unconstrained long_term_value portfolio (22.6M) but above every single option."""
    sc = scenario.model_copy(deep=True)
    sc.constraints.budget_ceiling_jpy = 20_000_000
    return sc


@pytest.fixture(scope="session")
def tight_rec(analysis: AnalysisResult, cfg: EngineConfig, tight_scenario: ClientScenario) -> Recommendation:
    return recommend(analysis, cfg=cfg, scenario=tight_scenario, sensitivity=False)
