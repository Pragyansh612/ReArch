"""Load the committed demo analyses (data/demo/*.json.gz) into the database. `make seed`."""

from __future__ import annotations

import gzip
import json
import threading
from pathlib import Path

from api.app.db import Analysis, now
from api.app.runs import RunService
from api.app.settings import Settings


def seed_demo(svc: RunService, settings: Settings, wait: bool = False) -> list[str]:
    """Load the demo analyses. The slow sensitivity job runs synchronously if `wait` (make seed), else in a background thread."""
    loaded: list[str] = []
    pending: list[str] = []
    manifest_path = settings.demo_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for gz in sorted(Path(settings.demo_dir).glob("*.json.gz")):
        analysis_id = gz.name.removesuffix(".json.gz")
        with svc.session() as s:
            if s.get(Analysis, analysis_id) is not None:
                continue
            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                text = fh.read()
            info = manifest.get(analysis_id, {})
            row = Analysis(id=analysis_id, name=json.loads(text)["meta"]["name"], repo=info.get("repo", "preloaded demo"), scope=json.dumps(info.get("scope", [])),
                           source="demo", status="done", message="preloaded demo analysis", created_at=now())
            s.add(row)
            s.commit()
            svc.store_analysis(s, row, text)
            run = svc.current_run(s, analysis_id).run
        pending.append(run.id)
        loaded.append(analysis_id)
    if settings.precompute_sensitivity:
        def work() -> None:
            for run_id in pending:
                svc.compute_sensitivity(run_id)  # blocking, but the work runs in a separate process

        if wait:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()
    return loaded


def main() -> None:
    from api.app.main import create_app

    app = create_app(seed=False)
    loaded = seed_demo(app.state.svc, app.state.settings, wait=True)
    print(f"seeded {loaded or 'nothing (already loaded)'} into {app.state.settings.db_url}")


if __name__ == "__main__":
    main()
