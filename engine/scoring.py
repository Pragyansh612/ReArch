"""Priorities: score each eligible strategy per module on absolute scales, pick the best, report the margin."""

from __future__ import annotations

from dataclasses import dataclass

from engine.config import CRITERIA, Criterion, EngineConfig, Priorities, Strategy
from engine.schema import CriterionScore, ScoredStrategy, StrategyChoice
from engine.strategies import OptionCalc

_RAW = {"cost": "cost_jpy", "risk": "risk_score", "speed": "duration_months", "long_term_value": "long_term_value"}


@dataclass
class Ranked:
    strategy: Strategy
    score: float
    criteria: list[CriterionScore]


def _raw(o: OptionCalc, criterion: Criterion) -> float:
    return float(getattr(o, _RAW[criterion]))


def goodness(criterion: Criterion, raw: float, cfg: EngineConfig) -> float:
    """Absolute 0..1 scale per criterion (see config `scoring`); never relative to the other options."""
    rule = cfg.scoring
    if criterion == "cost":
        return max(0.0, 1.0 - raw / rule.cost_ceiling_jpy)
    if criterion == "speed":
        return max(0.0, 1.0 - raw / rule.duration_ceiling_months)
    if criterion == "risk":
        return max(0.0, 1.0 - raw / 100.0)
    return min(1.0, raw / 100.0)


def rank(options: list[OptionCalc], weights: Priorities, cfg: EngineConfig) -> list[Ranked]:
    """Eligible options, best first. Ties break by the order of `strategies` in the config (cheaper first)."""
    ranked: list[Ranked] = []
    for o in (x for x in options if x.eligible):
        criteria: list[CriterionScore] = []
        for c in CRITERIA:
            g, w = round(goodness(c, _raw(o, c), cfg), 6), getattr(weights, c)  # contribution uses the shown value
            criteria.append(CriterionScore(criterion=c, raw=_raw(o, c), goodness=g, weight=w,
                                           contribution=round(100.0 * w * g, 4)))
        ranked.append(Ranked(o.strategy, round(sum(x.contribution for x in criteria), 4), criteria))
    order = {s: i for i, s in enumerate(cfg.strategies)}
    return sorted(ranked, key=lambda r: (-r.score, order[r.strategy]))


def choose(options: list[OptionCalc], weights: Priorities, profile: str, cfg: EngineConfig) -> StrategyChoice:
    ranked = rank(options, weights, cfg)
    best, second = ranked[0], ranked[1] if len(ranked) > 1 else None
    margin = round(best.score - second.score, 4) if second else None
    return StrategyChoice(
        profile=profile, weights=weights, chosen=best.strategy, score=best.score,
        runner_up=second.strategy if second else None, runner_up_score=second.score if second else None,
        margin=margin, close_call=margin is not None and margin < cfg.close_call_margin,
        ranking=[ScoredStrategy(strategy=r.strategy, score=r.score, criteria=r.criteria) for r in ranked])


def pick(options: list[OptionCalc], weights: Priorities, cfg: EngineConfig) -> Strategy:
    return rank(options, weights, cfg)[0].strategy
