"""Engine creation and schema setup for the local SQLite database."""

from sqlalchemy import Engine, event
from sqlmodel import SQLModel, create_engine

from verigrad.config import Settings
from verigrad.core.store import models  # noqa: F401  (registers tables on SQLModel.metadata)


def _enable_foreign_keys(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def get_engine(settings: Settings) -> Engine:
    """Engine for the configured database file; creates its folder if needed."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return make_engine(f"sqlite:///{settings.db_path}")


def init_db(engine: Engine) -> None:
    """Create any missing tables. No migrations tool yet (see docs/architecture.md)."""
    SQLModel.metadata.create_all(engine)
