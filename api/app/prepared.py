"""Scenario-independent facts about an analysis (health, packages, class scores), computed once and cached."""

from __future__ import annotations

from dataclasses import dataclass, field

from analyzer.schema import AnalysisResult
from engine.config import EngineConfig, load_engine_config
from engine.facts import build_contexts, build_module_facts, unit_facts
from engine.health import hotspots, unit_health
from engine.schema import ModuleHealth
from engine.workpackages import WorkPackage, build_work_packages

# ILLUSTRATIVE thresholds for the colour bands the UI draws (health 0-100, higher is better)
GOOD_MIN, FAIR_MIN = 60.0, 40.0


def band(score: float) -> str:
    return "good" if score >= GOOD_MIN else "fair" if score >= FAIR_MIN else "poor"


@dataclass
class PackageFacts:
    wp: WorkPackage
    loc: int
    health: ModuleHealth
    confidence: str


@dataclass
class Prepared:
    module_health: dict[str, ModuleHealth]
    packages: dict[str, PackageFacts]
    class_hotspot: dict[str, float] = field(default_factory=dict)  # fqn -> hotspot score 0-100
    class_package: dict[str, str] = field(default_factory=dict)


def prepare(result: AnalysisResult, cfg: EngineConfig | None = None) -> Prepared:
    cfg = cfg or load_engine_config()
    contexts = build_contexts(result)
    module_facts, _ = build_module_facts(result, cfg, contexts)
    packages: dict[str, PackageFacts] = {}
    owner: dict[str, str] = {}
    for wp in build_work_packages(result, cfg):
        f = unit_facts(result, cfg, wp.id, wp.kind, wp.classes, contexts[wp.module])
        packages[wp.id] = PackageFacts(wp, f.loc, unit_health(f, cfg), f.confidence)
        owner.update({c: wp.id for c in wp.classes})
    everything = cfg.model_copy(update={"hotspots": cfg.hotspots.model_copy(update={"top_n": len(result.classes) or 1})})
    return Prepared(module_health={m: unit_health(f, cfg) for m, f in module_facts.items()}, packages=packages,
                    class_hotspot={h.fqn: h.score for h in hotspots(result, everything)}, class_package=owner)
