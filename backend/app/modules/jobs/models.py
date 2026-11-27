"""Background jobs in PostgreSQL (ADR-0004). A job names what to work on; it holds no content."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.model_mixins import TimestampMixin, UUIDPrimaryKeyMixin

QUEUED, RUNNING, SUCCEEDED, FAILED = "queued", "running", "succeeded", "failed"
# The only list of statuses: the check constraint below is built from it.
STATUSES = (QUEUED, RUNNING, SUCCEEDED, FAILED)
OPEN = (QUEUED, RUNNING)
PROCESS_SOURCE = "process_source"
KINDS = (PROCESS_SOURCE,)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_one_of("kind", KINDS), name="kind_valid"),
        CheckConstraint(_one_of("status", STATUSES), name="status_valid"),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="attempts_valid"),
        CheckConstraint(
            f"(status = '{RUNNING}') = (locked_until IS NOT NULL)", name="lease_when_running"
        ),
        # One open job per thing: enqueueing again while one waits or runs adds nothing.
        Index(
            "uq_jobs_open_subject",
            "kind",
            "subject_id",
            unique=True,
            postgresql_where=_one_of("status", OPEN),
        ),
        Index("ix_jobs_status_run_after", "status", "run_after"),
    )

    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    # What the job works on, such as a knowledge source. No foreign key: the job outlives it.
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # While running: when the worker's claim ends, so another worker may take the job over.
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(50))  # from our own codes only
