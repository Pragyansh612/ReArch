"""Summaries of a run and the diff between two of them (what-if without persisting)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Summary(BaseModel):
    profile: str
    strategy_by_package: dict[str, str]
    strategy_mix: dict[str, int]
    migration_cost_jpy: int
    tco_jpy: int
    retain_tco_jpy: int
    tco_savings_vs_retain_jpy: int
    npv_vs_retain_jpy: int
    payback_quarter: int | None
    peak_investment_jpy: int
    finish_month: int | None
    within_budget: bool
    budget_binding: bool
    headlines: list[str]


class PickChange(BaseModel):
    package_id: str
    name: str
    before: str
    after: str


class Delta(BaseModel):
    migration_cost_jpy: int
    tco_jpy: int
    tco_savings_vs_retain_jpy: int
    npv_vs_retain_jpy: int
    peak_investment_jpy: int
    finish_month: int | None
    payback_quarter: int | None


class Diff(BaseModel):
    changed_picks: list[PickChange]
    delta: Delta


def summarize(rec: dict[str, Any], roadmap: dict[str, Any], profile: str) -> Summary:
    chosen = {c["package_id"]: c["strategy"] for c in roadmap["portfolio"]["constrained"]["choices"]}
    tco = retain = 0
    for wid, w in rec["work_packages"].items():
        by = {o["strategy"]: o for o in w["options"] if o["eligible"]}
        tco += by[chosen[wid]]["tco"]["tco_jpy"]
        retain += by["retain"]["tco"]["tco_jpy"]
    e = roadmap["economics"]
    return Summary(
        profile=profile, strategy_by_package=chosen, strategy_mix=roadmap["portfolio"]["constrained"]["strategy_mix"],
        migration_cost_jpy=roadmap["portfolio"]["constrained"]["total_migration_cost_jpy"], tco_jpy=tco, retain_tco_jpy=retain,
        tco_savings_vs_retain_jpy=retain - tco, npv_vs_retain_jpy=e["npv_vs_retain_jpy"], payback_quarter=e["payback_quarter"],
        peak_investment_jpy=e["peak_investment_jpy"], finish_month=roadmap["meta"]["finish_month"],
        within_budget=roadmap["portfolio"]["constrained"]["total_migration_cost_jpy"] <= roadmap["portfolio"]["budget_ceiling_jpy"],
        budget_binding=roadmap["portfolio"]["budget_binding"], headlines=[h["text"] for h in roadmap["headlines"]])


def diff(before: Summary, after: Summary, names: dict[str, str]) -> Diff:
    changed = [PickChange(package_id=p, name=names.get(p, p), before=before.strategy_by_package.get(p, "n/a"), after=after.strategy_by_package.get(p, "n/a"))
               for p in sorted(set(before.strategy_by_package) | set(after.strategy_by_package))
               if before.strategy_by_package.get(p) != after.strategy_by_package.get(p)]
    d = Delta(migration_cost_jpy=after.migration_cost_jpy - before.migration_cost_jpy, tco_jpy=after.tco_jpy - before.tco_jpy,
              tco_savings_vs_retain_jpy=after.tco_savings_vs_retain_jpy - before.tco_savings_vs_retain_jpy,
              npv_vs_retain_jpy=after.npv_vs_retain_jpy - before.npv_vs_retain_jpy,
              peak_investment_jpy=after.peak_investment_jpy - before.peak_investment_jpy,
              finish_month=None if before.finish_month is None or after.finish_month is None else after.finish_month - before.finish_month,
              payback_quarter=None if before.payback_quarter is None or after.payback_quarter is None else after.payback_quarter - before.payback_quarter)
    return Diff(changed_picks=changed, delta=d)
