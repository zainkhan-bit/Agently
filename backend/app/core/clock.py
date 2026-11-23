"""The one time source for application timestamps. Tests replace ``now``."""

from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)
