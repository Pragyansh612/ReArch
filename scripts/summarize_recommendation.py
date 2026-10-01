"""Plain-text digest of out/<name>.recommendation.json for review.

    python scripts/summarize_recommendation.py out/ofbiz.recommendation.json [--verbose]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def yen(n: float | None) -> str:
    if n is None:
        return "-"
    return f"JPY {n / 1e6:,.1f}M" if abs(n) >= 1e6 else f"JPY {n:,.0f}"


def main(path: str, verbose: bool) -> None:
    rec = json.loads(Path(path).read_text())
    profiles = list(rec["estate"])
    sel = rec["meta"]["selected_profile"]
    print(f"ANALYSIS {rec['meta']['analysis_name']} | client: {rec['meta']['scenario_client']} | selected profile: {sel}")
    for name, m in rec["modules"].items():
        c, h = m["criticality"], m["health"]
        print(f"\n== MODULE {name}: {m['loc']:,} LOC | health {h['score']:.1f} | criticality {c['value']} ({c['source']}, "
              f"heuristic {c['heuristic_value']}) | confidence {m['confidence']} | work packages {len(m['work_package_ids'])}")
        for p in profiles:
            r = m["rollups"][p]
            print(f"   rollup {p:16} migration {yen(r['migration_cost_jpy']):>12} | TCO {yen(r['tco_jpy']):>12} vs retain "
                  f"{yen(r['retain_tco_jpy']):>12} | {r['duration_months']:5.1f} mo | {list(r['strategy_by_work_package'].values())}")
        for wid in m["work_package_ids"]:
            w = rec["work_packages"][wid]
            wh = w["health"]
            drv = ", ".join(f"{k} -{next(x['contribution_points'] for x in wh['components'] if x['key'] == k):.1f}" for k in wh["top_drivers"])
            print(f"   -- {wid}: {w['name']} | {len(w['classes'])} classes, {w['loc']:,} LOC | health {wh['score']:.1f} ({drv})")
            retain = next(o for o in w["options"] if o["strategy"] == "retain")
            print("      " + " ; ".join(
                f"{o['strategy']}: " + ("INELIGIBLE" if not o["eligible"] else
                                         (f"mig {yen(o['migration_cost_jpy'])} TCO {yen(o['tco']['tco_jpy'])} pay {o['tco']['payback_year']}"
                                          + (" INFEASIBLE" if not o["feasible"] else "")))
                for o in w["options"]))
            for p in profiles if verbose else [sel]:
                ch = w["choices"][p]
                opt = next(o for o in w["options"] if o["strategy"] == ch["chosen"])
                t = opt["tco"]
                print(f"      {p:16} -> {ch['chosen']:11} TCO {yen(t['tco_jpy'])} vs retain {yen(retain['tco']['tco_jpy'])} "
                      f"(save {yen(t['savings_vs_retain_jpy'])}) payback {t['payback_year']} margin {ch['margin']:.1f}"
                      f"{' CLOSE' if ch['close_call'] else ''} (runner-up {ch['runner_up']})")
            flips = [f for f in w["sensitivity"] if f["flip_value"] is not None][:2]
            print("      flips:", "; ".join(f"{f['parameter']} {f['current_value']:g}->{f['flip_value']:.4g} => {f['new_strategy']}" for f in flips) or "none")
            bad = [(o["strategy"], o["infeasible_reasons"]) for o in w["options"] if not o["feasible"]]
            if bad and verbose:
                print("      infeasible:", bad)
    print("\nESTATE PORTFOLIO")
    for p, e in rec["estate"].items():
        print(f"   {p:16} mix {e['strategy_mix']} | migration {yen(e['total_migration_cost_jpy'])} | TCO {yen(e['total_tco_jpy'])} vs retain "
              f"{yen(e['retain_tco_jpy'])} (save {yen(e['tco_savings_vs_retain_jpy'])}, NPV {yen(e['npv_vs_retain_jpy'])}) | "
              f"{e['total_duration_months']:.1f} mo | budget ok {e['within_budget']} | close {len(e['close_calls'])}")
    ef = rec["estate_findings"]
    print(f"\nESTATE FINDING: dependencies {ef['outdated']} outdated / {ef['checked']} checked / {ef['declared']} declared")


if __name__ == "__main__":
    main(sys.argv[1], "--verbose" in sys.argv)
