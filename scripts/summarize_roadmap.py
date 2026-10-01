"""Plain-text digest of out/<name>.roadmap.json.   python scripts/summarize_roadmap.py out/ofbiz.roadmap.json"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def yen(n: float) -> str:
    return f"JPY {n / 1e6:,.1f}M" if abs(n) >= 1e6 else f"JPY {n:,.0f}"


def main(path: str) -> None:
    r = json.loads(Path(path).read_text())
    m, p, e = r["meta"], r["portfolio"], r["economics"]
    print(f"ROADMAP {m['analysis_name']} | profile {m['profile']} | capacity {m['capacity_people']} people ({m['teams']} teams) | finish month {m['finish_month']}")
    print(f"PORTFOLIO budget {yen(p['budget_ceiling_jpy'])} binding={p['budget_binding']}")
    for k in ("unconstrained", "constrained"):
        pf = p[k]
        print(f"   {k:14} {pf['strategy_mix']} | migration {yen(pf['total_migration_cost_jpy'])} | total score {pf['total_score']}")
    for d in p["downgrades"]:
        print(f"   DOWNGRADED {d['package_id']}: {d['unconstrained']} -> {d['constrained']} (score -{d['score_lost']}, saves {yen(d['migration_cost_saved_jpy'])})")
    print("RETAINED:", r["retained_packages"])
    print("\nWAVES")
    for w in r["waves"]:
        print(f"  {w['name']:34} months {w['start_month']}-{w['end_month']} | {yen(w['cost_jpy'])} | peak {w['peak_people']} people | {len(w['item_ids'])} items")
    print("\nITEMS (wave | months | people | cost | strategy | name | reasons)")
    for it in r["items"]:
        ev = f" cutovers {[(c['month'], c['hours']) for c in it['cutover_events']]}" if it["cutover_events"] else ""
        print(f"  W{it['wave']} | {it['start_month']:3}-{it['end_month']:3} | {it['people']:2} | {yen(it['cost_jpy']):>11} | {it['strategy']!s:11} | {it['name'][:52]:52} | "
              f"{','.join(c['code'] for c in it['reason_codes'])}{ev}")
    if r["unscheduled"]:
        print("UNSCHEDULED:", r["unscheduled"])
    print("\nUNLOCKS")
    for u in r["unlocks"]:
        print(f"  {u['name']:48} {u['status']:14} from month {u['available_from_month']} | blocked by {u['blocked_by'][:3]}")
    print(f"\nECONOMICS horizon {e['horizon_months']} mo | programme cost {yen(e['total_programme_cost_jpy'])} | payback quarter {e['payback_quarter']} | NPV vs retain {yen(e['npv_vs_retain_jpy'])} | peak investment {yen(e['peak_investment_jpy'])} (Q{e['peak_investment_quarter']})")
    for q in e["quarters"][::2]:
        print(f"   Q{q['quarter']:2} month {q['month_end']:2} spend {yen(q['programme_spend_jpy']):>11} | net vs retain {yen(q['net_cumulative_jpy']):>12} | run-rate {yen(q['roadmap_annual_run_rate_jpy'])} vs retain {yen(q['retain_annual_run_rate_jpy'])}")
    for k in e["kpis"]:
        if k["modelled"]:
            last = k["points"][-1]
            print(f"   KPI {k['objective']}: {k['current']} -> {last['value']} {k['unit']} at month {last['month_end']} (target {k['target']}, reached quarter {k['target_reached_quarter']})")
        else:
            print(f"   KPI {k['objective']}: {k['note']}")


if __name__ == "__main__":
    main(sys.argv[1])
