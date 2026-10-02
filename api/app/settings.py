"""Runtime settings, read from the environment (see docs/api.md)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
ENGINE_VERSION = "rearch-engine 0.3.0"  # part of every cache key: bump when model code changes results


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class Settings(BaseModel):
    demo_mode: bool = False  # DEMO_MODE: no POST /analyses (no cloning on a public server); preloaded analyses only
    data_dir: Path = ROOT / "data"
    demo_dir: Path = ROOT / "data" / "demo"  # committed, preloaded analyses (*.json.gz)
    database_url: str = ""  # DATABASE_URL; default: sqlite file in data_dir
    cors_origins: list[str] = ["http://localhost:3000"]  # plus CORS_ORIGIN (a production origin)
    path_roots: list[Path] = [ROOT / "targets", ROOT / "fixtures"]  # server paths accepted by POST /analyses must live here
    clone_timeout_s: float = 120.0
    analysis_timeout_s: float = 300.0
    max_repo_mb: int = 400
    max_classes: int = 25000
    seed_demo_on_start: bool = True  # in demo mode, load data/demo/*.json.gz when the database is empty
    precompute_sensitivity: bool = True  # compute flip points and breakevens in the background (seeded analyses, scenario edits)
    sensitivity_executor: str = "process"  # process: a separate process (no GIL contention with requests); inline: in-thread (tests)
    sensitivity_debounce_s: float = 2.0  # after the last edit of an analysis; only its latest run is computed

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'rearch.db'}"

    @classmethod
    def from_env(cls) -> Settings:
        origins = ["http://localhost:3000"]
        extra = os.environ.get("CORS_ORIGIN", "").strip()
        if extra:
            origins += [o.strip() for o in extra.split(",") if o.strip()]
        data_dir = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
        roots = [Path(p) for p in os.environ.get("PATH_ROOTS", "").split(":") if p] or [ROOT / "targets", ROOT / "fixtures"]
        return cls(demo_mode=_flag("DEMO_MODE"), data_dir=data_dir, database_url=os.environ.get("DATABASE_URL", ""),
                   cors_origins=origins, path_roots=roots)
