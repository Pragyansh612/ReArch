"""Business criticality (1-3): the tool proposes from usage and data-write intensity; the consultant confirms."""

from __future__ import annotations

from engine.config import EngineConfig, Override
from engine.facts import EstateFacts, ModuleFacts
from engine.schema import Criticality, CriticalityInputs


def propose(f: ModuleFacts, estate: EstateFacts, cfg: EngineConfig) -> tuple[int, CriticalityInputs]:
    rule = cfg.criticality
    inbound_share = f.inbound_total / estate.inbound_total if estate.inbound_total else 0.0
    write_share = f.db_writes / estate.writes_total if estate.writes_total else 0.0
    score = round(rule.inbound_weight * inbound_share + rule.write_weight * write_share, 6)
    value = 3 if score >= rule.high_min_score else 2 if score >= rule.medium_min_score else 1
    return value, CriticalityInputs(
        java_cross_module_fan_in=f.java_cross_module_fan_in, service_fan_in=f.service_fan_in,
        controller_fan_in=f.controller_fan_in, inbound_total=f.inbound_total, inbound_share=round(inbound_share, 6),
        data_writes=f.db_writes, write_share=round(write_share, 6), score=score)


def criticality(f: ModuleFacts, estate: EstateFacts, overrides: dict[str, Override], cfg: EngineConfig) -> Criticality:
    proposed, inputs = propose(f, estate, cfg)
    override = overrides.get(f.name)
    if override is None:
        return Criticality(value=proposed, source="heuristic", heuristic_value=proposed, inputs=inputs)
    return Criticality(value=override.criticality, source="override", heuristic_value=proposed, inputs=inputs,
                       override_reason=override.reason, status="confirmed_by_override")
