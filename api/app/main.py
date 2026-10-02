"""FastAPI application factory. `uvicorn api.app.main:app`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from api.app import errors
from api.app.db import Analysis, make_engine
from api.app.routes_analyses import router as analyses_router
from api.app.routes_runs import router as runs_router
from api.app.runs import RunService
from api.app.seed import seed_demo
from api.app.settings import Settings

DESCRIPTION = """ReArch API: deterministic legacy-code analysis, a modernization recommendation and a roadmap.
Every figure is computed by Python from facts; assumptions are ILLUSTRATIVE and the client scenario is fictional.
Any number can be explained with `GET /explain/{number_id}`."""


def create_app(settings: Settings | None = None, seed: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.db_url)
    svc = RunService(engine, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.demo_mode and settings.seed_demo_on_start and seed:
            with svc.session() as s:
                empty = s.exec(select(Analysis)).first() is None
            if empty:
                seed_demo(svc, settings)
        yield
        svc.shutdown()

    app = FastAPI(title="ReArch API", version="0.5.0", description=DESCRIPTION, lifespan=lifespan)
    app.state.svc, app.state.settings = svc, settings
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
    errors.install(app)
    app.include_router(analyses_router)
    app.include_router(runs_router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "demo" if settings.demo_mode else "full"}

    return app


app = create_app()
