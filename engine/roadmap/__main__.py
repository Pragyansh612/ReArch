"""CLI: python -m engine.roadmap <analysis.json> [--profile NAME] [--scenario FILE] [--out out/]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analyzer.schema import AnalysisResult
from engine.config import DEFAULT_SCENARIO
from engine.recommend import recommend
from engine.roadmap.build import build_roadmap
from engine.roadmap.config import load_roadmap_config
from engine.scenario import load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine.roadmap", description="Budget-constrained portfolio and wave roadmap.")
    parser.add_argument("analysis", help="analyzer output, e.g. out/ofbiz.json")
    parser.add_argument("--profile", help="preset, client_scenario (default) or cost=..,risk=..,speed=..,long_term_value=..")
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument("--out", default="out/")
    args = parser.parse_args(argv)
    path = Path(args.analysis)
    if not path.is_file():
        print(f"error: {path} not found (run `make analyze` first)", file=sys.stderr)
        return 2
    try:
        result = AnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))
        scenario = load_scenario(Path(args.scenario))
        rec = recommend(result, profile=args.profile or None, scenario=scenario, sensitivity=False)
        rm = build_roadmap(rec, result, scenario, load_roadmap_config(), rec.meta.selected_profile)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{result.meta.name}.roadmap.json"
    target.write_text(rm.model_dump_json(indent=2), encoding="utf-8")
    e, p = rm.economics, rm.portfolio
    print(f"{target}: profile={rm.meta.profile} constrained mix={p.constrained.strategy_mix} downgrades={len(p.downgrades)} "
          f"waves={len(rm.waves) - 1} finish_month={rm.meta.finish_month} programme JPY {e.total_programme_cost_jpy:,} "
          f"payback_quarter={e.payback_quarter} NPV JPY {e.npv_vs_retain_jpy:,} (ILLUSTRATIVE, FICTIONAL client)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
