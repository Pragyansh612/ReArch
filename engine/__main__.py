"""CLI: python -m engine <analysis.json> [--profile NAME|cost=..,risk=..,..] [--scenario FILE] [--out out/]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analyzer.schema import AnalysisResult
from engine.config import DEFAULT_SCENARIO
from engine.recommend import recommend
from engine.scenario import load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine", description="Scoring and strategy recommendation.")
    parser.add_argument("analysis", help="analyzer output, e.g. out/ofbiz.json")
    parser.add_argument("--profile", help="preset, client_scenario (default), or cost=0.4,risk=0.3,speed=0.2,long_term_value=0.1")
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO), help="client scenario YAML")
    parser.add_argument("--out", default="out/")
    args = parser.parse_args(argv)
    path = Path(args.analysis)
    if not path.is_file():
        print(f"error: {path} not found (run `make analyze` first)", file=sys.stderr)
        return 2
    result = AnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))
    try:
        rec = recommend(result, profile=args.profile or None, scenario=load_scenario(Path(args.scenario)))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{result.meta.name}.recommendation.json"
    target.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
    t = rec.estate[rec.meta.selected_profile]
    print(f"{target}: profile={rec.meta.selected_profile} mix={t.strategy_mix} migration=JPY {t.total_migration_cost_jpy:,} "
          f"TCO=JPY {t.total_tco_jpy:,} (retain JPY {t.retain_tco_jpy:,}) within_budget={t.within_budget} "
          f"(ILLUSTRATIVE assumptions, FICTIONAL client)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
