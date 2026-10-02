"""Measure API latency against a real server (HTTP, demo data). Starts uvicorn on a temporary database.

    python scripts/measure_api.py [--analysis ofbiz] [--port 8011]
"""

from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def timed(fn, n: int = 1):  # type: ignore[no-untyped-def]
    ms = []
    out = None
    for _ in range(n):
        t = time.perf_counter()
        out = fn()
        ms.append((time.perf_counter() - t) * 1000)
    return out, ms


def row(name: str, ms: list[float], extra: str = "") -> None:
    ms = sorted(ms)
    print(f"  {name:46} median {statistics.median(ms):7.1f} ms | min {ms[0]:7.1f} | max {ms[-1]:7.1f} | n={len(ms)} {extra}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", default="ofbiz")
    ap.add_argument("--port", type=int, default=8011)
    args = ap.parse_args()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "DEMO_MODE": "1", "DATA_DIR": tmp, "PATH_ROOTS": str(ROOT / "targets")}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.app.main:app", "--port", str(args.port), "--log-level", "warning"],
                              cwd=ROOT, env=env)
    base, a = f"http://127.0.0.1:{args.port}", args.analysis
    try:
        with httpx.Client(base_url=base, timeout=120) as c:
            started = time.perf_counter()
            while True:
                try:
                    if c.get("/health").status_code == 200 and c.get("/analyses").json():
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            print(f"server ready (seeded demo analyses) in {time.perf_counter() - started:.1f} s")
            started = time.perf_counter()
            while c.get(f"/analyses/{a}/recommendation").json()["run"]["sensitivity"] != "ready":
                time.sleep(0.2)
            print(f"background sensitivity (flip points + breakevens) ready after {time.perf_counter() - started:.1f} s more\n")
            print("reads (cached run):")
            row("GET /analyses/{id}", timed(lambda: c.get(f"/analyses/{a}"), 10)[1])
            r, ms = timed(lambda: c.get(f"/analyses/{a}/recommendation"), 10)
            row("GET /recommendation (one profile)", ms, f"{len(r.content) / 1000:.0f} KB")
            r, ms = timed(lambda: c.get(f"/analyses/{a}/roadmap"), 10)
            row("GET /roadmap", ms, f"{len(r.content) / 1000:.0f} KB")
            row("GET /classes?sort_by=hotspot&limit=20", timed(lambda: c.get(f"/analyses/{a}/classes?limit=20"), 10)[1])
            row("GET /graph?level=class&limit=100", timed(lambda: c.get(f"/analyses/{a}/graph?level=class&limit=100"), 10)[1])
            rid = c.get(f"/analyses/{a}/recommendation").json()["run"]["number_id_prefix"]
            row("GET /explain/{id}", timed(lambda: c.get(f"/explain/{rid}work_packages/order~1cycle-1/options/3/tco/tco_jpy"), 10)[1])
            print("\nrecompute (what the sliders trigger):")
            rates = [81000 + 1000 * i for i in range(12)]
            put_ms, server_ms = [], []
            for rate in rates:
                t = time.perf_counter()
                r = c.put(f"/analyses/{a}/scenario", json={"assumptions": {"daily_rate_jpy": rate}})
                put_ms.append((time.perf_counter() - t) * 1000)
                server_ms.append(r.json()["run"]["recompute_ms"])
            row("PUT /scenario (new version, full recompute)", put_ms, f"| server-side recompute median {statistics.median(server_ms):.0f} ms")
            weights = [{"cost": 0.1 + 0.02 * i, "risk": 0.3, "speed": 0.1, "long_term_value": 0.5 - 0.02 * i} for i in range(12)]
            wi = []
            for w in weights:
                t = time.perf_counter()
                c.post(f"/analyses/{a}/whatif", json={"priorities": w})
                wi.append((time.perf_counter() - t) * 1000)
            row("POST /whatif (priority sliders)", wi)
            row("GET /roadmap?profile=long_term_value (first, builds)", timed(lambda: c.get(f"/analyses/{a}/roadmap?profile=long_term_value"), 1)[1])
            row("GET /roadmap?profile=long_term_value (cached)", timed(lambda: c.get(f"/analyses/{a}/roadmap?profile=long_term_value"), 5)[1])
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
