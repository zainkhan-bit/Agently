"""Enqueue, claim and finish jobs (ADR-0004). Callers commit, except ``claim``."""

import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.modules.jobs.models import FAILED, OPEN, QUEUED, RUNNING, SUCCEEDED, Job

DEFAULT_ATTEMPTS = 3
BACKOFF = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=8))


def enqueue(db: Session, kind: str, subject_id: uuid.UUID) -> None:
    """Adds a job unless one for the same thing is already waiting or running. Does not commit."""
    now = clock.now()
    db.execute(
        insert(Job)
        .values(
            id=uuid.uuid4(),
            kind=kind,
            subject_id=subject_id,
            status=QUEUED,
            attempts=0,
            max_attempts=DEFAULT_ATTEMPTS,
            run_after=now,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["kind", "subject_id"],
            index_where=Job.status.in_(OPEN),
        )
    )


def claim(
    db: Session, lease: timedelta, give_up: Callable[[Session, Job], None] | None = None
) -> Job | None:
    """The next job that is due, or one whose worker's lease ran out. Commits.

    ``give_up`` records, in the same transaction, that a job's attempts all died with their
    workers, so that what it worked on does not show "in progress" forever.
    """
    now = clock.now()
    job = db.scalar(
        select(Job)
        .where(
            or_(
                and_(Job.status == QUEUED, Job.run_after <= now),
                and_(Job.status == RUNNING, Job.locked_until < now),
            )
        )
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.commit()
        return None
    if job.attempts >= job.max_attempts:  # its last attempt died with its worker
        _end(job, FAILED, "attempts_exhausted")
        if give_up is not None:
            give_up(db, job)
        db.commit()
        return claim(db, lease, give_up)
    job.status = RUNNING
    job.attempts += 1
    job.locked_until = now + lease
    job.updated_at = now
    db.commit()
    return job


def lock_if_mine(db: Session, job: Job) -> bool:
    """Lock the job's row. False when another worker took it over after our lease ran out:
    then this worker must change nothing.
    """
    claimed_until = job.locked_until
    current = db.scalar(
        select(Job)
        .where(Job.id == job.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (
        current is not None and current.status == RUNNING and current.locked_until == claimed_until
    )


def succeed(job: Job) -> None:
    _end(job, SUCCEEDED, None)


def fail(job: Job, code: str, *, retry: bool) -> bool:
    """Retries later when it may pass and attempts remain. Returns whether it will retry."""
    now = clock.now()
    if retry and job.attempts < job.max_attempts:
        job.status = QUEUED
        job.locked_until = None
        job.last_error = code
        job.run_after = now + BACKOFF[min(job.attempts - 1, len(BACKOFF) - 1)]
        job.updated_at = now
        return True
    _end(job, FAILED, code)
    return False


def _end(job: Job, status: str, code: str | None) -> None:
    job.status = status
    job.locked_until = None
    job.last_error = code
    job.updated_at = clock.now()
