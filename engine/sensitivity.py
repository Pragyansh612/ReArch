"""Which single assumption would flip a module's recommendation, and at what value."""

from __future__ import annotations

import math
from collections.abc import Callable

from engine.config import CRITERIA, EngineConfig, Priorities, Strategy
from engine.schema import Flip
from engine.scoring import pick
from engine.strategies import ModuleInputs, build_options

Evaluate = Callable[[float], Strategy]
_REFINE_ITERATIONS = 40


def _bisect(evaluate: Evaluate, inside: float, outside: float, base: Strategy, in_log_space: bool) -> float:
    """Boundary between a value that keeps `base` (inside) and one that flips it (outside)."""
    lo, hi = (math.log(inside), math.log(outside)) if in_log_space else (inside, outside)
    for _ in range(_REFINE_ITERATIONS):
        mid = (lo + hi) / 2
        value = math.exp(mid) if in_log_space else mid
        if evaluate(value) == base:
            lo = mid
        else:
            hi = mid
    return math.exp(hi) if in_log_space else hi


def _search(evaluate: Evaluate, current: float, base: Strategy, candidates: list[tuple[float, float]],
            in_log_space: bool) -> tuple[float, Strategy] | None:
    """`candidates` are (up, down) values of increasing distance. Returns the nearest flip and its new winner."""
    previous = (current, current)
    for up, down in candidates:
        found: list[tuple[float, Strategy]] = []
        for value, prev in ((up, previous[0]), (down, previous[1])):
            winner = evaluate(value)
            if winner != base:
                edge = _bisect(evaluate, prev, value, base, in_log_space)
                found.append((edge, evaluate(edge)))
        if found:
            return min(found, key=lambda f: abs(f[0] - current) if not in_log_space
                       else abs(math.log(f[0] / current)))
        previous = (up, down)
    return None


def _flip(parameter: str, current: float, hit: tuple[float, Strategy] | None, no_flip_note: str) -> Flip:
    if hit is None:
        return Flip(parameter=parameter, current_value=current, flip_value=None, change_pct=None,
                    new_strategy=None, note=no_flip_note)
    value, winner = hit
    change = abs(value - current) / current * 100.0 if current else abs(value) * 100.0
    word = "rises to" if value > current else "falls to"
    return Flip(parameter=parameter, current_value=current, flip_value=round(value, 6), change_pct=round(change, 2),
                new_strategy=winner, note=f"recommendation becomes {winner} when {parameter} {word} {value:.6g}")


def _scaled(cfg: EngineConfig, parameter: str, value: float) -> EngineConfig:
    if parameter == "daily_rate_jpy":
        return cfg.model_copy(update={"daily_rate_jpy": value})
    strategy = parameter.split(".", 1)[1]
    return cfg.model_copy(update={"base_days_per_kloc": {**cfg.base_days_per_kloc, strategy: value}})


def _reweighted(weights: Priorities, criterion: str, t: float) -> Priorities:
    """Set one weight to t and rescale the others proportionally so the weights still sum to 1."""
    current = getattr(weights, criterion)
    rest = 1.0 - current
    values = {c: (t if c == criterion else (getattr(weights, c) * (1.0 - t) / rest if rest else (1.0 - t) / 3))
              for c in CRITERIA}
    return Priorities(**values)


def find_flips(m: ModuleInputs, cfg: EngineConfig, weights: Priorities, base: Strategy) -> list[Flip]:
    steps, factor = cfg.sensitivity.steps, cfg.sensitivity.range_factor
    grid = [factor ** (k / steps) for k in range(1, steps + 1)]
    flips: list[Flip] = []
    multiplicative = ["daily_rate_jpy"] + [f"base_days_per_kloc.{s}" for s in cfg.strategies]
    for parameter in multiplicative:
        current = cfg.daily_rate_jpy if parameter == "daily_rate_jpy" else cfg.base_days_per_kloc[parameter.split(".")[1]]  # type: ignore[index]

        def evaluate(value: float, parameter: str = parameter) -> Strategy:
            return pick(build_options(m, _scaled(cfg, parameter, value)), weights, cfg)

        hit = _search(evaluate, current, base, [(current * g, current / g) for g in grid], in_log_space=True)
        note = f"no flip between x{1 / factor:g} and x{factor:g} of the current value"
        if parameter == "daily_rate_jpy":
            note += ": the rate scales every strategy's cost equally, so it changes totals but never the ranking"
        flips.append(_flip(parameter, current, hit, note))
    for criterion in CRITERIA:
        current = getattr(weights, criterion)

        def evaluate_w(value: float, criterion: str = criterion) -> Strategy:
            return pick(build_options(m, cfg), _reweighted(weights, criterion, value), cfg)

        candidates = [(current + (1.0 - current) * k / steps, current - current * k / steps)
                      for k in range(1, steps + 1)]
        flips.append(_flip(f"priority.{criterion}", current, _search(evaluate_w, current, base, candidates, False),
                           "no flip for any weight between 0 and 1 (other weights rescaled to keep the sum at 1)"))
    return sorted(flips, key=lambda f: (f.change_pct is None, f.change_pct if f.change_pct is not None else 0.0,
                                        f.parameter))
