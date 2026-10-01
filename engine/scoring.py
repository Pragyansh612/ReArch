"""Priorities: score each selectable strategy on absolute scales, pick the best, report the margin."""

from __future__ import annotations

from dataclasses import dataclass

from engine.config import CRITERIA, Criterion, EngineConfig, Priorities, Strategy
from engine.schema import CriterionScore, ScoredStrategy, StrategyChoice
from engine.strategies import OptionCalc


@dataclass
class Ranked:
    strategy: Strategy
    score: float
    criteria: list[CriterionScore]


def raw_value(o: OptionCalc, criterion: Criterion) -> float:
    return {"cost": float(o.tco_jpy), "risk": o.risk_score, "speed": o.duration_months, "long_term_value": o.value}[criterion]


def goodness(criterion: Criterion, raw: float, cfg: EngineConfig, retain_tco: float) -> float:
    """Absolute 0..1 scale per criterion (see config `scoring`); never relative to the other options.

    Cost is the horizon TCO scored against doing nothing: TCO equal to the retain TCO scores 1 - 1/ceiling.
    """
    rule = cfg.scoring
    if criterion == "cost":
        return 1.0 if retain_tco <= 0 else max(0.0, 1.0 - raw / (rule.cost_ratio_ceiling * retain_tco))
    if criterion == "speed":
        return max(0.0, 1.0 - raw / rule.duration_ceiling_months)
    if criterion == "risk":
        return max(0.0, 1.0 - raw / 100.0)
    return min(1.0, raw / 100.0)


def _criteria(o: OptionCalc, weights: Priorities, cfg: EngineConfig, retain_tco: float) -> list[tuple[Criterion, float, float, float, float]]:
    """(criterion, raw, goodness, weight, contribution); contribution uses the SHOWN (rounded) goodness."""
    out = []
    for c in CRITERIA:
        raw, w = raw_value(o, c), getattr(weights, c)
        g = round(goodness(c, raw, cfg, retain_tco), 6)
        out.append((c, raw, g, w, round(100.0 * w * g, 4)))
    return out


Crit = list[tuple[Criterion, float, float, float, float]]


def _scores(options: list[OptionCalc], weights: Priorities, cfg: EngineConfig) -> list[tuple[Strategy, float, Crit]]:
    retain_tco = float(next(o for o in options if o.strategy == "retain").tco_jpy)
    scored = []
    for o in (x for x in options if x.selectable):
        crit = _criteria(o, weights, cfg, retain_tco)
        scored.append((o.strategy, round(sum(c[4] for c in crit), 4), crit))
    order = {s: i for i, s in enumerate(cfg.strategies)}
    return sorted(scored, key=lambda r: (-r[1], order[r[0]]))


def rank(options: list[OptionCalc], weights: Priorities, cfg: EngineConfig) -> list[Ranked]:
    """Selectable options (eligible AND feasible), best first. Ties go to the earlier strategy in the config."""
    return [Ranked(s, score, [CriterionScore(criterion=c, raw=raw, goodness=g, weight=w, contribution=contrib)
                              for c, raw, g, w, contrib in crit]) for s, score, crit in _scores(options, weights, cfg)]


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
    return _scores(options, weights, cfg)[0][0]
