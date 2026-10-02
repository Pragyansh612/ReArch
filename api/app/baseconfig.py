"""Parsed config files, cached by modification time (PyYAML is slow: parsing dominated a scenario recompute)."""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from analyzer.config import DEFAULT_CONFIG
from engine.config import DEFAULT_SCENARIO, EngineConfig, load_engine_config
from engine.roadmap.config import RoadmapConfig, load_roadmap_config
from engine.scenario import ClientScenario, load_scenario


@lru_cache(maxsize=4)
def _engine(_mtime: int) -> dict[str, Any]:
    return load_engine_config().model_dump()


@lru_cache(maxsize=4)
def _roadmap(_mtime: int) -> dict[str, Any]:
    return load_roadmap_config().model_dump()


@lru_cache(maxsize=4)
def _scenario(_mtime: int) -> ClientScenario:
    return load_scenario()


def engine_dump() -> dict[str, Any]:
    return copy.deepcopy(_engine(DEFAULT_CONFIG.stat().st_mtime_ns))


def roadmap_dump() -> dict[str, Any]:
    return copy.deepcopy(_roadmap(DEFAULT_CONFIG.stat().st_mtime_ns))


def base_scenario() -> ClientScenario:
    return _scenario(DEFAULT_SCENARIO.stat().st_mtime_ns).model_copy(deep=True)


def base_engine_config() -> EngineConfig:
    return EngineConfig.model_validate(engine_dump())


def base_roadmap_config() -> RoadmapConfig:
    return RoadmapConfig.model_validate(roadmap_dump())
