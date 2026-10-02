"""Budget-constrained portfolio: one selectable option per package, maximising the value-at-stake-weighted score.

Objective: the sum over packages of (package weight x the chosen option's priority-weighted score 0-100), where a package's weight
is its 5-year do-nothing (retain) TCO, i.e. its share of the estate's do-nothing cost. A big package therefore counts for more than a
small one; two otherwise identical packages get weights in proportion to their size of spend.

Exact: dynamic programming over the Pareto frontier of (cost, objective) states (a state is dropped only when another state is
at least as cheap and at least as good). Scores are integers (four decimals x 10,000) and weights are whole yen, so the objective is an
exact integer and there is no floating-point tie noise. Ties are broken deterministically: higher objective, then lower total cost,
then the lexicographically smallest strategy order.
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


def package_weights(rec: Recommendation) -> dict[str, int]:
    """Value at stake per package: its do-nothing (retain) TCO over the planning horizon, in whole yen."""
    out: dict[str, int] = {}
    for wid, w in rec.work_packages.items():
        retain = next(o for o in w.options if o.strategy == "retain")
        out[wid] = max(1, retain.tco.tco_jpy if retain.tco else 1)
    return out


def select(options: dict[str, list[Opt]], budget: int, order: dict[Strategy, int],
           weights: dict[str, int] | None = None) -> dict[str, Opt]:
    ids = sorted(options)
    w = weights or {p: 1 for p in ids}
    frontier: list[tuple[int, int, tuple[int, ...]]] = [(0, 0, ())]
    for pid in ids:
        cand = [(c + o.cost, s + o.score_int * w[pid], picks + (order[o.strategy],))
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


def _portfolio(chosen: dict[str, Opt], weights: dict[str, int]) -> Portfolio:
    mix: dict[str, int] = {}
    for o in chosen.values():
        mix[o.strategy] = mix.get(o.strategy, 0) + 1
    total_weight = sum(weights[p] for p in chosen)
    return Portfolio(
        total_score=round(sum(weights[p] * o.score_int for p, o in chosen.items()) / (SCALE * total_weight), 4),
        total_unweighted_score=round(sum(o.score_int for o in chosen.values()) / SCALE, 4),
        total_migration_cost_jpy=sum(o.cost for o in chosen.values()),
        choices=[PortfolioChoice(package_id=p, strategy=o.strategy, score=o.score_int / SCALE,
                                 weight=round(weights[p] / total_weight, 6), migration_cost_jpy=o.cost)
                 for p, o in sorted(chosen.items())], strategy_mix=dict(sorted(mix.items())))


def build_selection(rec: Recommendation, profile: str, budget: int) -> tuple[PortfolioSelection, dict[str, Strategy]]:
    options = package_options(rec, profile)
    weights = package_weights(rec)
    order = {s: i for i, s in enumerate(rec.assumptions["config"]["strategies"])}
    unconstrained = {pid: next(o for o in opts if o.strategy == rec.work_packages[pid].choices[profile].chosen)
                     for pid, opts in options.items()}
    constrained = select(options, budget, order, weights)
    total_weight = sum(weights.values())
    downgrades = [
        Downgrade(package_id=pid, name=rec.work_packages[pid].name, unconstrained=unconstrained[pid].strategy,
                  constrained=constrained[pid].strategy,
                  score_lost=round((unconstrained[pid].score_int - constrained[pid].score_int) / SCALE, 4),
                  weighted_score_lost=round(weights[pid] * (unconstrained[pid].score_int - constrained[pid].score_int) / (SCALE * total_weight), 4),
                  migration_cost_saved_jpy=unconstrained[pid].cost - constrained[pid].cost,
                  reason=f"total migration cost of the unconstrained portfolio exceeds the budget ceiling of JPY {budget:,}")
        for pid in sorted(options) if unconstrained[pid].strategy != constrained[pid].strategy]
    selection = PortfolioSelection(
        profile=profile, weights=rec.estate[profile].weights, budget_ceiling_jpy=budget,
        method="exact dynamic programming over the (cost, objective) Pareto frontier",
        objective="sum over packages of (share of the estate's 5-year do-nothing TCO) x (priority-weighted score of the chosen option)",
        budget_binding=sum(o.cost for o in unconstrained.values()) > budget, unconstrained=_portfolio(unconstrained, weights),
        constrained=_portfolio(constrained, weights), downgrades=downgrades)
    return selection, {pid: o.strategy for pid, o in constrained.items()}
