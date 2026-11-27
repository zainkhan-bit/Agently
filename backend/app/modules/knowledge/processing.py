"""Turn a source into chunks. Runs in the worker, never in a web request.

No database connection is held while the child process extracts the text. Afterwards the source
is locked and checked again: one deleted meanwhile stays deleted, and its result is dropped.
Logs carry ids and codes only.
"""

import json
import logging
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import clock
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.knowledge import storage
from app.modules.knowledge.chunking import chunk
from app.modules.knowledge.models import (
    FAILED,
    PENDING,
    PROCESSING,
    READY,
    KnowledgeChunk,
    KnowledgeSource,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60
# How long a claim lasts: the timeout, plus time to store the chunks.
LEASE = timedelta(seconds=TIMEOUT_SECONDS + 60)
# Failures that may pass on another try. Everything else is in the document itself.
RETRYABLE = {"processing_timeout", "processing_failed"}
CODES = {
    "text_empty",
    "text_unreadable",
    "text_too_long",
    "pages_too_many",
    "processing_timeout",
    "processing_failed",
    "file_missing",
}
BACKEND_DIR = Path(__file__).resolve().parents[3]


def process_source(db: Session, job: Job) -> None:
    """Handle one claimed job. Commits."""
    if not jobs.lock_if_mine(db, job):
        db.rollback()
        return
    source = _locked_source(db, job)
    if source is None:  # deleted before its turn
        jobs.succeed(job)
        db.commit()
        return
    source.status, source.error_code = PROCESSING, None
    source.updated_at = clock.now()
    kind, storage_name = source.kind, source.storage_name
    db.commit()  # gives the connection back: extraction can take a while

    path = storage.path_of(storage_name)
    outcome = _extract(path, kind) if path.is_file() else "file_missing"
    if isinstance(outcome, str):
        record_failure(db, job, outcome)
        return
    _store(db, job, outcome)


def give_up(db: Session, job: Job) -> None:
    """Every attempt died with its worker: the source fails. Does not commit."""
    source = _locked_source(db, job)
    if source is not None:
        source.status, source.error_code = FAILED, "processing_failed"
        source.updated_at = clock.now()


def command(kind: str, path: Path) -> list[str]:
    return [sys.executable, "-m", "app.modules.knowledge.extract", kind, str(path)]


def _extract(path: Path, kind: str):
    """The pages, or a failure code."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed module, our own arguments
            command(kind, path),
            cwd=BACKEND_DIR,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "processing_timeout"
    except OSError:
        return "processing_failed"
    # stderr is never read: a crash's message may quote the document.
    try:
        result = json.loads(done.stdout)
    except (ValueError, UnicodeDecodeError):
        return "processing_failed"
    if not isinstance(result, dict):
        return "processing_failed"
    if "error" in result:
        return result["error"] if result["error"] in CODES else "processing_failed"
    pages = result.get("pages")
    if not isinstance(pages, list) or not all(
        isinstance(item, list)
        and len(item) == 2
        and (item[0] is None or (type(item[0]) is int and item[0] >= 1))
        and isinstance(item[1], str)
        for item in pages
    ):
        return "processing_failed"
    return [(page, text.replace("\x00", "")) for page, text in pages]


def _locked_source(db: Session, job: Job) -> KnowledgeSource | None:
    return db.scalar(
        select(KnowledgeSource)
        .where(KnowledgeSource.id == job.subject_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _store(db: Session, job: Job, pages) -> None:
    if not jobs.lock_if_mine(db, job):  # taken over by another worker meanwhile
        db.rollback()
        return
    source = _locked_source(db, job)
    if source is None:
        jobs.succeed(job)  # deleted meanwhile: nothing to keep
        db.commit()
        return
    pieces = chunk(pages)
    if not pieces:
        db.rollback()
        record_failure(db, job, "text_empty")
        return
    # Replaces, never adds: a job that runs twice keeps one set of chunks.
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
    db.add_all(
        KnowledgeChunk(
            source_id=source.id,
            workspace_id=source.workspace_id,
            agent_id=source.agent_id,
            sequence=piece.sequence,
            page=piece.page,
            content=piece.content,
        )
        for piece in pieces
    )
    source.status, source.error_code = READY, None
    source.updated_at = clock.now()
    jobs.succeed(job)
    db.commit()
    logger.info("source processed (%s, %d chunks)", source.id, len(pieces))


def record_failure(db: Session, job: Job, code: str) -> None:
    """Fail the job, retrying when it may pass, and show it on the source. Commits."""
    if not jobs.lock_if_mine(db, job):
        db.rollback()
        return
    source = _locked_source(db, job)
    retrying = jobs.fail(job, code, retry=code in RETRYABLE)
    if source is not None:
        source.status, source.error_code = (PENDING, None) if retrying else (FAILED, code)
        source.updated_at = clock.now()
    db.commit()
    logger.warning("source not processed (%s, %s, retry=%s)", job.subject_id, code, retrying)
