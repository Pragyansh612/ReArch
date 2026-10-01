"""CLI: python -m analyzer <repo path> [--scope DIR ...] [--name NAME] [--out out/]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analyzer.analyze import analyze
from analyzer.config import DEFAULT_CONFIG


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analyzer", description="Deterministic legacy-code analysis.")
    parser.add_argument("repo", help="path to a local repository (git URLs: clone first, see Makefile)")
    parser.add_argument("--scope", nargs="*", default=[], help="directories relative to repo to analyse")
    parser.add_argument("--name", help="output name (default: repo directory name)")
    parser.add_argument("--out", default="out/", help="output directory")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    if not repo.is_dir():
        print(f"error: {repo} is not a directory", file=sys.stderr)
        return 2
    result = analyze(repo, args.scope, name=args.name, config_path=Path(args.config))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{result.meta.name}.json"
    target.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    t = result.totals
    print(f"{target}: {t.main_java_classes} classes, {t.modules} modules, {t.main_java_loc} LOC, "
          f"{len(result.findings)} findings, {result.meta.runtime_seconds}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
