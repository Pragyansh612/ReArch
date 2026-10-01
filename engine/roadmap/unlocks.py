"""What modernization unlocks: a deterministic mapping from modernized packages to data/AI opportunities. No LLM."""

from __future__ import annotations

from typing import Literal

from engine.config import Strategy
from engine.roadmap.config import RoadmapConfig
from engine.roadmap.schema import Opportunity
from engine.schema import Recommendation


def evaluate(rec: Recommendation, strategy_by_pkg: dict[str, Strategy], completion: dict[str, int | None],
             rcfg: RoadmapConfig) -> list[Opportunity]:
    rank = rcfg.foundations.strategy_rank
    out: list[Opportunity] = []
    for u in rcfg.unlocks:
        prerequisites: list[str] = []
        blocked: list[str] = []
        text: list[str] = []
        missing = False
        for req in u.requires:
            pkgs = [w for w in rec.work_packages.values() if w.module == req.module]
            text.append(f"{req.module}: packages holding at least {req.min_loc_share:.0%} of its code reach {req.min_strategy} or beyond")
            if not pkgs:
                missing = True
                blocked.append(f"{req.module} (module not in the analysed scope)")
                continue
            total = sum(w.loc for w in pkgs)
            ok = [w for w in pkgs if rank[strategy_by_pkg[w.id]] >= rank[req.min_strategy]]
            if sum(w.loc for w in ok) / total >= req.min_loc_share:
                prerequisites += [w.id for w in ok]
            else:
                blocked += [f"{w.id} ({strategy_by_pkg[w.id]})" for w in pkgs if w not in ok]
        status: Literal["unlocked", "not_unlocked", "module_not_analysed"] = (
            "module_not_analysed" if missing else "not_unlocked" if blocked else "unlocked")
        months = [completion.get(p) for p in prerequisites]
        available = None
        if status == "unlocked" and all(m is not None for m in months):
            available = max((m for m in months if m is not None), default=0) + 1
        out.append(Opportunity(
            id=u.id, name=u.name, kind=u.kind, description=u.description, status=status, requirements=text,
            prerequisite_packages=sorted(set(prerequisites)), available_from_month=available, blocked_by=sorted(blocked)))
    return out
