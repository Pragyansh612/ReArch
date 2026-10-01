"""CLI: python -m engine <analysis.json> [--profile NAME|cost=..,risk=..,..] [--overrides FILE] [--out out/]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analyzer.schema import AnalysisResult
from engine.config import DEFAULT_OVERRIDES, load_overrides
from engine.recommend import recommend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine", description="Scoring and strategy recommendation.")
    parser.add_argument("analysis", help="analyzer output, e.g. out/ofbiz.json")
    parser.add_argument("--profile", help="preset name, or custom weights cost=0.4,risk=0.3,speed=0.2,long_term_value=0.1")
    parser.add_argument("--overrides", default=str(DEFAULT_OVERRIDES), help="criticality overrides YAML")
    parser.add_argument("--out", default="out/")
    args = parser.parse_args(argv)
    path = Path(args.analysis)
    if not path.is_file():
        print(f"error: {path} not found (run `make analyze` first)", file=sys.stderr)
        return 2
    result = AnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))
    try:
        rec = recommend(result, profile=args.profile or None,
                        overrides=load_overrides(result.meta.name, Path(args.overrides)))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{result.meta.name}.recommendation.json"
    target.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
    totals = rec.estate[rec.meta.selected_profile]
    print(f"{target}: profile={rec.meta.selected_profile} total=JPY {totals.total_cost_jpy:,} "
          f"{totals.total_effort_days:,.0f} days {totals.total_duration_months:.1f} months "
          f"(ILLUSTRATIVE assumptions); close calls: {totals.close_calls or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
