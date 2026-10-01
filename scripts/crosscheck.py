"""Independent cross-check of analyzer output: cloc for LOC, plain grep for DB-coupling lines.

Shares no parsing code with the analyzer. Usage:
    python scripts/crosscheck.py <repo> out/<name>.json [--scope DIR ...]
Exit code 0 always; differences are printed so they can be explained in docs/methodology.md.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CLOC = shutil.which("cloc") or str(ROOT / ".tools/node_modules/.bin/cloc")


def java_main_dirs(repo: Path, scope: list[str]) -> list[str]:
    bases = [repo / s for s in scope] or [repo]
    return sorted(str(p.relative_to(repo)) for b in bases for p in b.rglob("src/main/java") if p.is_dir())


def cloc_by_file(repo: Path, dirs: list[str]) -> dict[str, int]:
    out = subprocess.run([CLOC, "--by-file", "--json", "--include-lang=Java", *dirs], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    return {k: v["code"] for k, v in data.items() if k not in ("header", "SUM")}


def grep_lines(repo: Path, dirs: list[str], regex: str) -> set[tuple[str, int]]:
    proc = subprocess.run(["grep", "-rnE", "--include=*.java", regex, *dirs], cwd=repo,
                          capture_output=True, text=True, check=False)  # grep exits 1 on no match
    hits = set()
    for line in proc.stdout.splitlines():
        file, num, _ = line.split(":", 2)
        hits.add((file, int(num)))
    return hits


def pattern_regex(patterns: list[dict[str, str]]) -> str:
    parts = [(re.escape(p["receiver"]) if p.get("receiver") else "") + r"\." + re.escape(p["method"]) + r"\("
             for p in patterns]
    return "|".join(parts)


def line_text(repo: Path, file: str, num: int) -> str:
    return (repo / file).read_text(errors="replace").splitlines()[num - 1].strip()[:110]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("result")
    ap.add_argument("--scope", nargs="*", default=[])
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    res = json.loads(Path(args.result).read_text())
    cfg = yaml.safe_load((ROOT / "config/assumptions.yaml").read_text())["analysis"]
    dirs = java_main_dirs(repo, args.scope)
    if not dirs:
        sys.exit("no src/main/java directories found")

    print("== LOC: analyzer vs cloc (per file, Java 'code' lines)")
    cloc = cloc_by_file(repo, dirs)
    mine = {c["file"]: c["loc"] for c in res["classes"].values()}
    diffs = {f: (mine[f], cloc.get(f)) for f in mine if mine[f] != cloc.get(f)}
    print(f"files: analyzer={len(mine)} cloc={len(cloc)}  total LOC: analyzer={sum(mine.values())} "
          f"cloc={sum(cloc.values())}  files differing={len(diffs)}")
    for f, (a, c) in sorted(diffs.items())[:15]:
        print(f"  {f}: analyzer={a} cloc={c}")
    only_cloc = sorted(set(cloc) - set(mine))
    if only_cloc:
        print(f"  files only cloc saw ({len(only_cloc)}): {only_cloc[:5]}")

    ignore = set(cfg["db_coupling"]["ignore_classes"])
    for kind in ("jdbc", "entity_engine"):
        grep = grep_lines(repo, dirs, pattern_regex(cfg["db_coupling"][kind]))
        got = {(d["file"], d["line"]) for d in res["db_coupling"]["instances"] if d["type"] == kind}
        print(f"\n== {kind}: analyzer={len(got)} grep-lines={len(grep)}")
        for label, items in (("grep only", sorted(grep - got)), ("analyzer only", sorted(got - grep))):
            print(f"  {label}: {len(items)}")
            for f, n in items[:12]:
                skipped = " [ignored class]" if Path(f).stem in ignore else ""
                print(f"    {f}:{n}{skipped}  {line_text(repo, f, n)}")


if __name__ == "__main__":
    main()
