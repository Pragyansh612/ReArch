"""Breakeven: the yearly maintenance spend at which the recommendation would change.

The model's maintenance baseline is its weakest number. Instead of tuning it, we report how far it would have to move
(for each package, under the selected profile) before another strategy overtakes the chosen one, and before retain
stops being best or loses to every alternative.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable

from engine.config import EngineConfig, Priorities, Strategy
from engine.scenario import ClientScenario
from engine.schema import Breakeven, Overtake
from engine.scoring import _scores
from engine.strategies import UnitInputs, build_options


def baseline_maintenance(m: UnitInputs, cfg: EngineConfig) -> float:
    from engine.strategies import model_maintenance

    return model_maintenance(m, cfg) if m.maintenance_override is None else m.maintenance_override


def _nearest(holds: Callable[[float], bool], x0: float, grid: list[float]) -> tuple[float, str] | None:
    """Nearest value (searching up and down from x0 in log space) where the condition becomes true, refined by bisection."""
    prev_up = prev_down = x0
    for g in grid:
        found: list[tuple[float, str]] = []
        for x, prev, direction in ((x0 * g, prev_up, "higher"), (x0 / g, prev_down, "lower")):
            if holds(x):
                lo, hi = math.log(prev), math.log(x)
                for _ in range(40):
                    mid = (lo + hi) / 2
                    lo, hi = (lo, mid) if holds(math.exp(mid)) else (mid, hi)
                found.append((math.exp(hi), direction))
        if found:
            return min(found, key=lambda f: abs(math.log(f[0] / x0)))
        prev_up, prev_down = x0 * g, x0 / g
    return None


def compute_breakeven(m: UnitInputs, cfg: EngineConfig, scenario: ClientScenario, weights: Priorities,
                      chosen: Strategy) -> Breakeven:
    base = baseline_maintenance(m, cfg)
    rule = cfg.breakeven
    grid = [rule.range_factor ** (k / rule.steps) for k in range(1, rule.steps + 1)]
    cache: dict[float, dict[Strategy, float]] = {}

    def scores(x: float) -> dict[Strategy, float]:
        if x not in cache:
            options = build_options(dataclasses.replace(m, maintenance_override=x), cfg, scenario)
            cache[x] = {s: score for s, score, _ in _scores(options, weights, cfg)}
        return cache[x]

    selectable = list(scores(base))
    overtaking: list[Overtake] = []
    for s in (x for x in selectable if x != chosen):
        hit = _nearest(lambda x, s=s: scores(x)[s] > scores(x)[chosen], base, grid)  # type: ignore[misc]
        overtaking.append(Overtake(strategy=s, breakeven_jpy_per_year=round(hit[0], 2) if hit else None,
                                   multiple_of_baseline=round(hit[0] / base, 4) if hit else None,
                                   direction=hit[1] if hit else None))  # type: ignore[arg-type]
    stops = loses = None
    if "retain" in selectable and base > 0:
        others = [s for s in selectable if s != "retain"]
        if others and chosen == "retain":
            hit = _nearest(lambda x: max(scores(x)[s] for s in others) > scores(x)["retain"], base, grid)
            stops = round(hit[0], 2) if hit else None
        if others:
            hit = _nearest(lambda x: min(scores(x)[s] for s in others) > scores(x)["retain"], base, grid)
            loses = round(hit[0], 2) if hit else None
    note = (f"searched yearly maintenance between JPY {base / rule.range_factor:,.0f} and JPY {base * rule.range_factor:,.0f}; "
            "None means no change inside that range")
    return Breakeven(baseline_jpy_per_year=round(base, 2), chosen=chosen,
                     overtaking=sorted(overtaking, key=lambda o: (o.multiple_of_baseline is None, abs(math.log(o.multiple_of_baseline or 1.0)))),
                     retain_stops_being_best_jpy_per_year=stops,
                     retain_loses_to_every_alternative_jpy_per_year=loses, note=note)
