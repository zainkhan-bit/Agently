"""The background worker (ADR-0004): one job at a time, outside every web request.

    backend> .venv\\Scripts\\python -m app.worker

Stop it with Ctrl+C. Several workers may run: each job is claimed by one of them.
"""

import logging
import signal
import sys
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logs import configure_logging
from app.models import Base  # noqa: F401 - registers every table
from app.modules.jobs import service as jobs
from app.modules.jobs.models import PROCESS_SOURCE, Job
from app.modules.knowledge import processing, storage

logger = logging.getLogger(__name__)

IDLE_SECONDS = 2.0
SWEEP_EVERY_SECONDS = 600.0
HANDLERS = {PROCESS_SOURCE: processing.process_source}
# After a crash: records the failure, retrying while attempts remain. Commit.
FAILURE_HANDLERS = {PROCESS_SOURCE: processing.record_failure}


def run_once(db: Session | None = None) -> bool:
    """Handle the next due job, if any. Returns whether there was one."""
    if db is None:
        with get_session_factory()() as session:
            return run_once(session)
    job = jobs.claim(db, processing.LEASE, _give_up)
    if job is None:
        return False
    try:
        HANDLERS[job.kind](db, job)
    except Exception as error:  # noqa: BLE001 - its message may hold private text
        db.rollback()
        logger.error("job failed (%s, %s)", job.id, type(error).__name__)
        job = db.get(Job, job.id, populate_existing=True)
        if job is not None:
            FAILURE_HANDLERS[job.kind](db, job, "processing_failed")
    return True


def _give_up(db: Session, job: Job) -> None:
    if job.kind == PROCESS_SOURCE:
        processing.give_up(db, job)


def sweep() -> None:
    with get_session_factory()() as db:
        removed = storage.sweep(db)
    if removed:
        logger.info("removed %d knowledge file(s) without a record", removed)


def main() -> int:
    configure_logging(get_settings().log_level)
    stopping = False

    def stop(*_) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logger.info("worker started")
    swept = 0.0
    while not stopping:
        try:
            if time.monotonic() - swept > SWEEP_EVERY_SECONDS:
                swept = time.monotonic()
                sweep()
            busy = run_once()
        except Exception as error:  # noqa: BLE001 - keep working; the database may come back
            logger.error("worker step failed (%s)", type(error).__name__)
            busy = False
        if not busy:
            time.sleep(IDLE_SECONDS)
    logger.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
