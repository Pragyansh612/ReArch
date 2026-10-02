"""SQLite via SQLModel. JSON documents are stored zlib-compressed."""

from __future__ import annotations

import json
import zlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine


def now() -> datetime:
    return datetime.now(UTC)


def pack(doc: Any) -> bytes:
    return zlib.compress(json.dumps(doc, separators=(",", ":")).encode("utf-8"), 6)


def unpack(blob: bytes) -> Any:
    return json.loads(zlib.decompress(blob))


class Analysis(SQLModel, table=True):
    """Immutable analyzer output (the JSON itself lives in a compressed file)."""

    id: str = Field(primary_key=True)
    name: str
    repo: str = ""
    scope: str = "[]"  # JSON list
    source: str = "user"  # user | demo
    status: str = "queued"  # queued | cloning | analyzing | done | failed
    message: str = ""
    created_at: datetime = Field(default_factory=now)
    finished_at: datetime | None = None
    content_hash: str = ""
    result_file: str = ""
    classes: int = 0
    loc: int = 0


class ScenarioVersion(SQLModel, table=True):
    """One immutable version of a scenario for an analysis; a PUT that changes anything adds a row."""

    id: int | None = Field(default=None, primary_key=True)
    analysis_id: str = Field(index=True)
    version: int
    created_at: datetime = Field(default_factory=now)
    content: bytes = b""  # packed ScenarioState
    note: str = ""


class Run(SQLModel, table=True):
    """A recommendation for (analysis x effective inputs), cached by a hash of those inputs."""

    id: str = Field(primary_key=True)  # first 16 hex characters of input_hash
    analysis_id: str = Field(index=True)
    input_hash: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=now)
    recommendation: bytes = b""  # packed Recommendation (no sensitivity)
    state: bytes = b""  # packed ScenarioState the run was computed from


class RunArtifact(SQLModel, table=True):
    """Derived documents of a run: roadmap per profile, sensitivity (slow, computed in the background)."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    kind: str  # roadmap | sensitivity
    key: str = ""  # profile for roadmaps
    content: bytes = b""
    created_at: datetime = Field(default_factory=now)


def make_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    SQLModel.metadata.create_all(engine)
    return engine


__all__ = ["Analysis", "Run", "RunArtifact", "ScenarioVersion", "Session", "make_engine", "now", "pack", "unpack"]
