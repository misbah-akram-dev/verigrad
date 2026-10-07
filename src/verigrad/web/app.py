"""FastAPI application factory. Run with `make dev`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from verigrad import __version__
from verigrad.config import Settings, get_settings
from verigrad.core.jobs.runner import JobRunner
from verigrad.core.store.db import get_engine, init_db
from verigrad.core.store.repository import fail_interrupted_jobs
from verigrad.web.fetch_routes import router as fetch_router
from verigrad.web.routes import router

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = get_engine(settings)
        init_db(engine)
        with Session(engine) as session:
            if interrupted := fail_interrupted_jobs(session):
                log.warning("marked %d interrupted job(s) as failed", interrupted)
        app.state.engine = engine
        app.state.runner = JobRunner(engine, settings)
        yield
        app.state.runner.shutdown()
        engine.dispose()

    app = FastAPI(title="Verigrad", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    app.include_router(fetch_router)
    return app


app = create_app()
