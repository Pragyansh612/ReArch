"""Budget-constrained portfolio: one selectable option per package, maximising the total priority-weighted score.

Exact: dynamic programming over the Pareto frontier of (cost, score) states (a state is dropped only when another state is
at least as cheap and at least as good). Scores are integers (four decimals x 10,000) so there is no floating-point
tie noise. Ties are broken deterministically: higher total score, then lower total cost, then the lexicographically
smallest strategy order. Package-size-blind: every package's score counts equally (documented limitation).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.config import Strategy
from engine.roadmap.schema import Downgrade, Portfolio, PortfolioChoice, PortfolioSelection
from engine.schema import Recommendation

SCALE = 10_000


@dataclass(frozen=True)
class Opt:
    strategy: Strategy
    score_int: int
    cost: int


def package_options(rec: Recommendation, profile: str) -> dict[str, list[Opt]]:
    """Selectable (eligible and feasible) options per package with the profile's score and the migration cost."""
    out: dict[str, list[Opt]] = {}
    for wid, w in sorted(rec.work_packages.items()):
        cost = {o.strategy: o.migration_cost_jpy or 0 for o in w.options}
        out[wid] = [Opt(s.strategy, round(s.score * SCALE), cost[s.strategy]) for s in w.choices[profile].ranking]
    return out


def select(options: dict[str, list[Opt]], budget: int, order: dict[Strategy, int]) -> dict[str, Opt]:
    ids = sorted(options)
    frontier: list[tuple[int, int, tuple[int, ...]]] = [(0, 0, ())]
    for pid in ids:
        cand = [(c + o.cost, s + o.score_int, picks + (order[o.strategy],))
                for c, s, picks in frontier for o in options[pid] if c + o.cost <= budget]
        cand.sort(key=lambda t: (t[0], -t[1], t[2]))
        frontier, best = [], -1
        for state in cand:
            if state[1] > best:
                frontier.append(state)
                best = state[1]
    _cost, _score, picks = min(frontier, key=lambda t: (-t[1], t[0], t[2]))
    by_index = {v: k for k, v in order.items()}
    return {pid: next(o for o in options[pid] if o.strategy == by_index[i]) for pid, i in zip(ids, picks, strict=True)}


def _portfolio(chosen: dict[str, Opt]) -> Portfolio:
    mix: dict[str, int] = {}
    for o in chosen.values():
        mix[o.strategy] = mix.get(o.strategy, 0) + 1
    return Portfolio(
        total_score=round(sum(o.score_int for o in chosen.values()) / SCALE, 4),
        total_migration_cost_jpy=sum(o.cost for o in chosen.values()),
        choices=[PortfolioChoice(package_id=p, strategy=o.strategy, score=o.score_int / SCALE, migration_cost_jpy=o.cost)
                 for p, o in sorted(chosen.items())], strategy_mix=dict(sorted(mix.items())))


def build_selection(rec: Recommendation, profile: str, budget: int) -> tuple[PortfolioSelection, dict[str, Strategy]]:
    options = package_options(rec, profile)
    order = {s: i for i, s in enumerate(rec.assumptions["config"]["strategies"])}
    unconstrained = {pid: next(o for o in opts if o.strategy == rec.work_packages[pid].choices[profile].chosen)
                     for pid, opts in options.items()}
    constrained = select(options, budget, order)
    downgrades = [
        Downgrade(package_id=pid, name=rec.work_packages[pid].name, unconstrained=unconstrained[pid].strategy,
                  constrained=constrained[pid].strategy,
                  score_lost=round((unconstrained[pid].score_int - constrained[pid].score_int) / SCALE, 4),
                  migration_cost_saved_jpy=unconstrained[pid].cost - constrained[pid].cost,
                  reason=f"total migration cost of the unconstrained portfolio exceeds the budget ceiling of JPY {budget:,}")
        for pid in sorted(options) if unconstrained[pid].strategy != constrained[pid].strategy]
    selection = PortfolioSelection(
        profile=profile, weights=rec.estate[profile].weights, budget_ceiling_jpy=budget,
        method="exact dynamic programming over the (cost, score) Pareto frontier",
        budget_binding=sum(o.cost for o in unconstrained.values()) > budget, unconstrained=_portfolio(unconstrained),
        constrained=_portfolio(constrained), downgrades=downgrades)
    return selection, {pid: o.strategy for pid, o in constrained.items()}
