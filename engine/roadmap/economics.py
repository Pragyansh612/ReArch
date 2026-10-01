"""Programme economics: cumulative cash flow by quarter against doing nothing, payback, NPV, peak investment, KPIs."""

from __future__ import annotations

from engine.config import Strategy
from engine.roadmap.schema import Economics, Item, KpiPoint, KpiTrajectory, QuarterPoint
from engine.scenario import ClientScenario
from engine.schema import Recommendation


def build_economics(rec: Recommendation, items: list[Item], strategy_by_pkg: dict[str, Strategy], completion: dict[str, int | None],
                    scenario: ClientScenario, discount_rate: float) -> Economics:
    horizon = scenario.constraints.planning_horizon_years * 12
    parts = ("maintenance", "run", "change")
    base = {k: 0.0 for k in parts}
    retain_month = [0.0] * (horizon + 1)
    roadmap_month = [0.0] * (horizon + 1)
    comp_retain = {k: 0.0 for k in parts}
    comp_roadmap = {k: [0.0] * (horizon + 1) for k in parts}
    for pid, w in rec.work_packages.items():
        retain = next(o for o in w.options if o.strategy == "retain").tco
        chosen = next(o for o in w.options if o.strategy == strategy_by_pkg[pid]).tco
        assert retain is not None and chosen is not None
        before = {"maintenance": retain.baseline_maintenance_jpy_per_year, "run": retain.baseline_run_jpy_per_year,
                  "change": retain.baseline_change_jpy_per_year}
        after = {"maintenance": chosen.steady_state_maintenance_jpy, "run": chosen.steady_state_run_jpy,
                 "change": chosen.steady_state_change_jpy}
        done = completion.get(pid)
        for k in parts:
            base[k] += before[k]
            comp_retain[k] += before[k]
        for m in range(1, horizon + 1):
            state = after if done is not None and m > done else before
            for k in parts:
                comp_roadmap[k][m] += state[k]
            retain_month[m] += sum(before.values()) / 12
            roadmap_month[m] += sum(state.values()) / 12
    spend = [0] * (horizon + 1)
    for it in items:
        for offset, amount in enumerate(it.monthly_spend_jpy):
            if it.start_month + offset <= horizon:
                spend[it.start_month + offset] += amount
    cum_retain = cum_roadmap = 0.0
    net = [0.0] * (horizon + 1)
    npv = 0.0
    quarters: list[QuarterPoint] = []
    for m in range(1, horizon + 1):
        cum_retain += retain_month[m]
        cum_roadmap += roadmap_month[m] + spend[m]
        net[m] = cum_retain - cum_roadmap
        npv += (retain_month[m] - roadmap_month[m] - spend[m]) / (1.0 + discount_rate) ** (m / 12.0)
        if m % 3 == 0:
            quarters.append(QuarterPoint(
                quarter=m // 3, month_end=m, programme_spend_jpy=sum(spend[m - 2:m + 1]),
                roadmap_cumulative_cost_jpy=round(cum_roadmap), retain_cumulative_cost_jpy=round(cum_retain),
                net_cumulative_jpy=round(net[m]), roadmap_annual_run_rate_jpy=round(roadmap_month[m] * 12),
                retain_annual_run_rate_jpy=round(retain_month[m] * 12)))
    total_spend = sum(spend)
    payback = None
    if total_spend > 0:
        dipped = False
        for q in quarters:
            dipped = dipped or q.net_cumulative_jpy < 0
            if q.net_cumulative_jpy >= 0 and (dipped or q.quarter == 1):
                payback = q.quarter
                break
    worst = min(range(1, horizon + 1), key=lambda m: net[m]) if horizon else 0
    peak = max(0.0, -net[worst]) if horizon else 0.0
    kpis: list[KpiTrajectory] = []
    for o in scenario.objectives:
        key = {"maintenance_cost": "maintenance", "run_cost": "run"}.get(o.id)
        if key is None:
            kpis.append(KpiTrajectory(objective=o.id, label=o.label, unit=o.unit, modelled=False, current=o.current, target=o.target,
                                      note="not modelled: the engine has no cause-and-effect model for this KPI", points=[],
                                      target_reached_quarter=None))
            continue
        pts = [KpiPoint(quarter=q.quarter, month_end=q.month_end,
                        value=round(o.current - (comp_retain[key] - comp_roadmap[key][q.month_end]) / 1e6, 3)) for q in quarters]
        reached = next((p.quarter for p in pts if p.value <= o.target), None)
        kpis.append(KpiTrajectory(
            objective=o.id, label=o.label, unit=o.unit, modelled=True, current=o.current, target=o.target,
            note="client KPI (whole ERP) minus the model's saving in the analysed scope; the model's baseline for that scope "
                 "differs from the scope-adjusted KPI (see kpi_reconciliation)", points=pts, target_reached_quarter=reached))
    return Economics(
        horizon_months=horizon, discount_rate=discount_rate, quarters=quarters, total_programme_cost_jpy=total_spend,
        payback_quarter=payback, npv_vs_retain_jpy=round(npv), peak_investment_jpy=round(peak),
        peak_investment_quarter=(worst + 2) // 3 if peak > 0 else None, kpis=kpis)
