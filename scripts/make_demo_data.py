"""Compress analyzer outputs from out/ into the committed demo data: data/demo/*.json.gz + manifest.json."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = {
    "ofbiz": {"repo": "https://github.com/apache/ofbiz-framework (commit c572aa78)",
              "scope": ["applications/order", "applications/product", "applications/party", "applications/accounting"]},
    "legacy-sample": {"repo": "fixtures/legacy-sample", "scope": []},
}


def main() -> None:
    target = ROOT / "data" / "demo"
    target.mkdir(parents=True, exist_ok=True)
    for name in DEMO:
        raw = (ROOT / "out" / f"{name}.json").read_bytes()
        with gzip.open(target / f"{name}.json.gz", "wb", compresslevel=9) as fh:
            fh.write(raw)
        print(f"{name}: {len(raw):,} bytes -> {(target / f'{name}.json.gz').stat().st_size:,} bytes gzipped")
    (target / "manifest.json").write_text(json.dumps(DEMO, indent=2) + "\n")


if __name__ == "__main__":
    main()
