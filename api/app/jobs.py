"""Background analysis jobs: validate the repo, clone (https only), analyse in a subprocess with a timeout, store the result."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from api.app.db import Analysis, now
from api.app.errors import ApiError
from api.app.runs import RunService
from api.app.settings import ROOT, Settings

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$")
SCOPE_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def validate_repo(repo: str, settings: Settings) -> tuple[str, str]:
    """('url', repo) for a plain https URL, ('path', resolved) for a directory under an allowed root. Anything else is refused."""
    if repo.startswith(("http://", "https://")):
        u = urlparse(repo)
        if u.scheme != "https" or not u.hostname or u.username or u.password or any(c.isspace() for c in repo) or repo.startswith("-"):
            raise ApiError(422, "invalid_repo", "repo must be a plain https URL without credentials")
        return "url", repo
    path = Path(repo)
    if not path.is_absolute():
        raise ApiError(422, "invalid_repo", "repo must be an https git URL or an absolute server path")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise ApiError(422, "invalid_repo", f"{repo} is not a directory on the server")
    if not any(resolved == r.resolve() or r.resolve() in resolved.parents for r in settings.path_roots):
        raise ApiError(403, "path_not_allowed", "server paths are only accepted under the configured roots")
    return "path", str(resolved)


def validate_scope(scope: list[str]) -> list[str]:
    for s in scope:
        if s.startswith("/") or ".." in s.split("/") or not SCOPE_RE.match(s):
            raise ApiError(422, "invalid_scope", f"scope entry '{s}' must be a relative directory without '..'")
    return scope


def _dir_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and ".git" not in f.parts) / 1e6


def create_job(svc: RunService, repo: str, scope: list[str], name: str | None, settings: Settings) -> Analysis:
    if name is not None and not NAME_RE.match(name):
        raise ApiError(422, "invalid_name", "name may contain letters, digits, '.', '_' and '-' (max 60)")
    kind, target = validate_repo(repo, settings)
    scope = validate_scope(scope)
    derived = re.sub(r"[^A-Za-z0-9._-]", "-", Path(urlparse(target).path if kind == "url" else target).name.removesuffix(".git")) or "analysis"
    row = Analysis(id=uuid.uuid4().hex[:12], name=name or derived[:60], repo=repo, scope=json.dumps(scope), source="user", status="queued")
    with svc.session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
    return row


def _set(svc: RunService, analysis_id: str, **fields: object) -> None:
    with svc.session() as s:
        row = svc.get_analysis(s, analysis_id)
        for k, v in fields.items():
            setattr(row, k, v)
        s.add(row)
        s.commit()


def run_job(svc: RunService, analysis_id: str) -> None:
    """Runs in a background thread. Never raises: every failure becomes status=failed with a message."""
    settings = svc.settings
    work = settings.data_dir / "work" / analysis_id
    try:
        with svc.session() as s:
            row = svc.get_analysis(s, analysis_id)
            repo, scope, name = row.repo, json.loads(row.scope), row.name
        kind, target = validate_repo(repo, settings)
        source = Path(target)
        if kind == "url":
            _set(svc, analysis_id, status="cloning", message="cloning (shallow)")
            work.mkdir(parents=True, exist_ok=True)
            source = work / "repo"
            subprocess.run(["git", "clone", "--depth", "1", "--single-branch", "--", target, str(source)], check=True, capture_output=True,
                           timeout=settings.clone_timeout_s, env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"})
            size = _dir_mb(source)
            if size > settings.max_repo_mb:
                raise ApiError(422, "repo_too_large", f"the repository is {size:.0f} MB; the limit is {settings.max_repo_mb} MB")
        _set(svc, analysis_id, status="analyzing", message="analysing")
        out = work / "out"
        out.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "analyzer", str(source), "--name", name, "--out", str(out)] + (["--scope", *scope] if scope else [])
        started = time.perf_counter()
        subprocess.run(cmd, check=True, capture_output=True, timeout=settings.analysis_timeout_s, cwd=ROOT)
        text = (out / f"{name}.json").read_text(encoding="utf-8")
        classes = json.loads(text)["totals"]["main_java_classes"]
        if classes > settings.max_classes:
            raise ApiError(422, "analysis_too_large", f"{classes} classes exceed the limit of {settings.max_classes}")
        with svc.session() as s:
            svc.store_analysis(s, svc.get_analysis(s, analysis_id), text)
        _set(svc, analysis_id, message=f"done in {time.perf_counter() - started:.1f}s")
        with svc.session() as s:
            run = svc.current_run(s, analysis_id).run
        if settings.precompute_sensitivity:
            svc.schedule_sensitivity(analysis_id, run.id)
    except subprocess.TimeoutExpired as exc:
        _set(svc, analysis_id, status="failed", message=f"timed out after {exc.timeout:g}s", finished_at=now())
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or ["command failed"]
        _set(svc, analysis_id, status="failed", message=tail[0][:300], finished_at=now())
    except ApiError as exc:
        _set(svc, analysis_id, status="failed", message=exc.message, finished_at=now())
    except Exception as exc:  # noqa: BLE001  a background job must never raise: every failure becomes status=failed
        _set(svc, analysis_id, status="failed", message=f"{type(exc).__name__}: {exc}"[:300], finished_at=now())
    finally:
        shutil.rmtree(work, ignore_errors=True)
