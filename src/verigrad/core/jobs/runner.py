"""Background job runner: one worker thread with its own event loop.

Playwright never runs on FastAPI's event loop. With `--reload`, uvicorn runs on a
SelectorEventLoop on Windows, which can't start Playwright's driver subprocess. Each job runs
in `asyncio.Runner` on the worker thread with a ProactorEventLoop (Windows) — whatever loop
uvicorn picked. A single worker also runs jobs one at a time, which keeps fetching polite.
"""

import asyncio
import logging
import sys
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.config import Settings
from verigrad.core.fetch.polite import DomainThrottle
from verigrad.core.jobs.models import JobProgress
from verigrad.core.store import repository as repo
from verigrad.core.store.models import JobStatus, utcnow

log = logging.getLogger(__name__)

JobWork = Callable[[], Coroutine[Any, Any, JobStatus]]


def job_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    return asyncio.ProactorEventLoop if sys.platform == "win32" else None


class JobRunner:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.engine = engine
        self.settings = settings
        # Long-lived so the per-domain delay also holds between consecutive jobs.
        self.throttle = DomainThrottle(settings.fetch_delay_seconds)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verigrad-job")

    def submit(self, job_id: int, work: JobWork) -> Future[None]:
        return self._executor.submit(self._run, job_id, work)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: int, work: JobWork) -> None:
        with Session(self.engine) as session:
            repo.update_job(session, job_id, status=JobStatus.RUNNING, started_at=utcnow())
        try:
            with asyncio.Runner(loop_factory=job_loop_factory()) as runner:
                status = runner.run(work())
        except Exception as exc:
            log.exception("job %s crashed", job_id)
            with Session(self.engine) as session:
                repo.update_job(
                    session,
                    job_id,
                    status=JobStatus.FAILED,
                    error=f"{type(exc).__name__}: {exc}"[:500],
                    finished_at=utcnow(),
                )
            return
        with Session(self.engine) as session:
            repo.update_job(session, job_id, status=status, finished_at=utcnow())


def save_progress(engine: Engine, job_id: int, progress: JobProgress) -> None:
    with Session(engine) as session:
        repo.update_job(session, job_id, progress=progress.model_dump_json())
