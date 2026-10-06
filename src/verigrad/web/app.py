"""FastAPI application factory. Run with `make dev`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from verigrad import __version__
from verigrad.config import Settings, get_settings
from verigrad.core.store.db import get_engine, init_db
from verigrad.web.routes import router

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = get_engine(settings)
        init_db(engine)
        app.state.engine = engine
        yield
        engine.dispose()

    app = FastAPI(title="Verigrad", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    return app


app = create_app()
