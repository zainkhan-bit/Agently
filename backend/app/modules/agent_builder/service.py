"""Turns answers into a draft. Saves nothing: a draft becomes an agent only if a person saves it.

Answers, prompts and model output are private and untrusted: never stored, never logged.
"""

import json
import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, RateLimitError
from app.modules.agent_builder.prompt import build_messages
from app.modules.agent_builder.schemas import AgentDraft, Answers
from app.modules.agents.service import ensure_room
from app.modules.identity import throttle
from app.modules.providers.contract import (
    KNOWN_ERRORS,
    Completion,
    Message,
    Provider,
    ProviderError,
    ProviderNotConfiguredError,
)
from app.modules.workspaces.service import WorkspaceContext

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 6_000
MAX_OUTPUT_CHARACTERS = 64_000
# A call holds one of the server's 40 worker threads, which every request needs.
_slots = threading.BoundedSemaphore(8)


class InvalidDraftError(AppError):
    status_code = 502
    code = "draft_invalid"
    message = "The AI returned a draft that cannot be used. Please try again."


class GenerationLimitError(RateLimitError):
    message = "You or your workspace generated too many drafts. Please try again later."


def generate_draft(
    db: Session, context: WorkspaceContext, provider: Provider | None, answers: Answers
) -> AgentDraft:
    if provider is None:
        raise ProviderNotConfiguredError()
    ensure_room(db, context)
    if not _slots.acquire(blocking=False):
        logger.warning("draft generation failed (no free slot)")
        raise ProviderError()
    try:
        limits = throttle.generation_limits(context.user_id, context.workspace.id)
        if throttle.record_attempt(db, limits) is None:
            raise GenerationLimitError()
        # The call can take long: give the database connection back first.
        db.commit()
        text = _call(provider, build_messages(answers.model_dump()))
    finally:
        _slots.release()
    if isinstance(text, ProviderError):
        raise text
    return parse_draft(text)


def _call(provider: Provider, messages: list[Message]) -> str | ProviderError:
    """Returns errors instead of raising: theirs may hold private text, also as a cause."""
    try:
        completion = provider.complete(
            messages,
            timeout_seconds=get_settings().provider_timeout_seconds,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        if isinstance(completion, Completion) and isinstance(completion.text, str):
            return completion.text
        failure = ProviderError
    except Exception as error:  # noqa: BLE001 - nothing about it may be logged
        # Only the class survives, and only a known one.
        failure = type(error) if type(error) in KNOWN_ERRORS else ProviderError
    logger.warning("draft generation failed (%s)", failure.code)
    return failure()


def _unique_keys(pairs: list[tuple[str, Any]]) -> None:
    """The last of two equal keys would win, so a reviewer of the text could be misled."""
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError


def parse_draft(text: str) -> AgentDraft:
    if len(text) <= MAX_OUTPUT_CHARACTERS:
        try:
            draft = AgentDraft.model_validate_json(text)
            json.loads(text, object_pairs_hook=_unique_keys)
            return draft
        except (ValueError, RecursionError):
            pass  # holds the text: neither logged nor kept as a cause
    logger.warning("draft generation failed (%s)", InvalidDraftError.code)
    raise InvalidDraftError()
