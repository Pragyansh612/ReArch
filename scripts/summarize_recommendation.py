"""Plain-text digest of out/<name>.recommendation.json (and its analysis) for review.

    python scripts/summarize_recommendation.py out/ofbiz.recommendation.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def yen(n: int | None) -> str:
    return "-" if n is None else f"JPY {n / 1e6:,.1f}M" if n >= 1e6 else f"JPY {n:,}"


def main(path: str) -> None:
    rec = json.loads(Path(path).read_text())
    profiles = list(rec["estate"])
    print(f"ANALYSIS {rec['meta']['analysis_name']}  selected profile: {rec['meta']['selected_profile']}")
    for name, m in rec["modules"].items():
        h, c = m["health"], m["criticality"]
        drivers = ", ".join(f"{k} (-{next(x['contribution_points'] for x in h['components'] if x['key'] == k):.1f})"
                            for k in h["top_drivers"])
        print(f"\n== {name}: {m['loc']:,} LOC | health {h['score']:.1f} | drivers: {drivers}")
        print(f"   criticality {c['value']} ({c['source']}; heuristic {c['heuristic_value']}, score {c['inputs']['score']:.3f}) "
              f"| confidence {m['confidence']} (java share {m['java_share']}) | inbound {m['inbound_references']}")
        for p in profiles:
            ch = m["choices"][p]
            opt = next(o for o in m["options"] if o["strategy"] == ch["chosen"])
            close = " CLOSE CALL" if ch["close_call"] else ""
            print(f"   {p:16} -> {ch['chosen']:11} {yen(opt['cost_jpy']):>14} {opt['duration_months']:6.1f} mo "
                  f"margin {ch['margin']:5.1f} (runner-up {ch['runner_up']}){close}")
        print("   options:", "; ".join(f"{o['strategy']} {yen(o['cost_jpy'])}/{o['duration_months']:.1f}mo/risk {o['risk_score']:.0f}/value {o['long_term_value']:.0f}"
                                       if o["eligible"] else f"{o['strategy']} INELIGIBLE" for o in m["options"]))
        flips = [f for f in m["sensitivity"] if f["flip_value"] is not None][:3]
        print("   flips:", "; ".join(f"{f['parameter']} {f['current_value']:g}->{f['flip_value']:.4g} ({f['change_pct']:.0f}% change) => {f['new_strategy']}"
                                     for f in flips) or "none")
        print("   no flip:", ", ".join(f["parameter"] for f in m["sensitivity"] if f["flip_value"] is None))
    print("\nESTATE")
    for p, e in rec["estate"].items():
        print(f"   {p:16} {yen(e['total_cost_jpy']):>14} {e['total_effort_days']:9,.0f} days {e['total_duration_months']:6.1f} mo  "
              f"{e['strategy_by_module']}  close: {e['close_calls']}")
    print("\nHOTSPOTS (top 10)")
    for h in rec["hotspots"][:10]:
        print(f"   {h['score']:5.1f} {h['fqn'].split('.', 3)[-1]:55} loc={h['loc']:5} cx={h['complexity']:5} {h['flags']}")


if __name__ == "__main__":
    main(sys.argv[1])
