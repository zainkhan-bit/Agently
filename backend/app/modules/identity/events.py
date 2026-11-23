"""Authentication event log. Takes explicit safe fields only: no emails, passwords or tokens."""

import logging
import uuid
from dataclasses import dataclass

logger = logging.getLogger("app.auth.events")


@dataclass(frozen=True)
class RequestInfo:
    ip: str
    request_id: str


def log(event: str, info: RequestInfo, user_id: uuid.UUID | None = None) -> None:
    logger.info("event=%s user_id=%s ip=%s request_id=%s", event, user_id, info.ip, info.request_id)
