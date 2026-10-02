"""The slow part of a run (flip points and breakevens, ~4 s on OFBiz), written to run in a separate process.

It lives in its own module so a spawned worker imports only what it needs, and so the web server's GIL is never held by it.
"""

from __future__ import annotations

import gzip
from typing import Any

from analyzer.schema import AnalysisResult
from api.app.scenario_state import ScenarioState, build_scenario, effective_configs
from engine.recommend import recommend


def compute_job(analysis_file: str, state: dict[str, Any]) -> dict[str, Any]:
    with gzip.open(analysis_file, "rt", encoding="utf-8") as fh:
        result = AnalysisResult.model_validate_json(fh.read())
    scenario_state = ScenarioState.model_validate(state)
    cfg, _ = effective_configs(scenario_state)
    full = recommend(result, cfg=cfg, scenario=build_scenario(scenario_state, result.meta.name), sensitivity=True)
    return {wid: {"sensitivity": [f.model_dump(mode="json") for f in w.sensitivity],
                  "breakeven": w.breakeven.model_dump(mode="json") if w.breakeven else None}
            for wid, w in full.work_packages.items()}
