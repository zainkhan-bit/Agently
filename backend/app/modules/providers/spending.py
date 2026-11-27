"""The server-wide spending limit. Wraps a real provider, so nothing can call it without paying.

The worst case is reserved before a call and corrected after a successful one. It is given back
when the call was never sent, or refused before any work (``ProviderError.uncharged``). Every other
outcome keeps it, because the provider may have charged for it.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.database import limit_write_time
from app.modules.providers.contract import (
    Completion,
    Message,
    Provider,
    ProviderBudgetError,
    ProviderError,
    ProviderTimeoutError,
    Stream,
    TextPiece,
)
from app.modules.providers.models import ModelSpec
from app.modules.providers.tables import ProviderSpend

logger = logging.getLogger(__name__)

NANO = 1_000_000_000
TOKENS_PER_MESSAGE = 100  # roles and separators, generously
WARN_PERCENT = 80
_LOCK = 7_310_531  # any constant: one reservation at a time, across processes


def worst_case(spec: ModelSpec, messages: Sequence[Message], max_output_tokens: int) -> int:
    """Nano-dollars. A token is at least one byte, and the output limit includes thinking."""
    sent = sum(len(m.content.encode()) + TOKENS_PER_MESSAGE for m in messages)
    if sent > spec.max_input_tokens or not 0 < max_output_tokens <= spec.max_output_tokens:
        raise ProviderError()
    return spec.cost(sent, max_output_tokens)


class MeteredProvider:
    def __init__(
        self, inner: Provider, spec: ModelSpec, new_session: Callable[[], Session]
    ) -> None:
        self._inner = inner
        self._spec = spec
        self._new_session = new_session

    def complete(
        self, messages: Sequence[Message], *, timeout_seconds: float, max_output_tokens: int
    ) -> Completion:
        reservation, left = self._pay(messages, timeout_seconds, max_output_tokens)
        try:
            completion = self._inner.complete(
                messages, timeout_seconds=left, max_output_tokens=max_output_tokens
            )
        except ProviderError as error:
            if error.uncharged:
                self._correct(reservation, cost_nano_usd=0)
            raise
        self._settle(reservation, completion)
        return completion

    def stream(
        self,
        messages: Sequence[Message],
        *,
        timeout_seconds: float,
        max_output_tokens: int,
        cancel: threading.Event | None = None,
    ) -> Stream:
        reservation, left = self._pay(messages, timeout_seconds, max_output_tokens)
        inner = self._inner.stream(
            messages, timeout_seconds=left, max_output_tokens=max_output_tokens, cancel=cancel
        )
        try:
            while True:
                # Not around the yield: an error thrown in by the reader gives nothing back.
                try:
                    item = next(inner)
                except StopIteration:
                    return
                except ProviderError as error:
                    if error.uncharged:
                        self._correct(reservation, cost_nano_usd=0)
                    raise
                if not isinstance(item, TextPiece):
                    self._settle(reservation, item)
                yield item
        finally:
            inner.close()

    def _pay(
        self, messages: Sequence[Message], timeout_seconds: float, max_output_tokens: int
    ) -> tuple[uuid.UUID, float]:
        started = time.monotonic()
        cost = worst_case(self._spec, messages, max_output_tokens)
        reservation = None
        try:
            with self._new_session() as session:
                reservation = _reserve(session, self._spec.name, cost)
        except ProviderBudgetError:
            raise
        except Exception as error:  # noqa: BLE001 - not recorded, so not sent
            logger.warning("provider call refused (spending: %s)", type(error).__name__)
        if reservation is None:
            raise ProviderError()
        left = timeout_seconds - (time.monotonic() - started)
        if left <= 0:
            self._correct(reservation, cost_nano_usd=0)
            raise ProviderTimeoutError()
        return reservation, left

    def _settle(self, reservation: uuid.UUID, completion: Completion) -> None:
        self._correct(
            reservation,
            cost_nano_usd=self._spec.cost(completion.input_tokens, completion.output_tokens),
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )

    def _correct(self, reservation: uuid.UUID, **values: int) -> None:
        """If this fails, the reservation stays. An answer is already paid for, so it is kept."""
        try:
            with self._new_session() as session:
                limit_write_time(session)
                session.execute(
                    update(ProviderSpend).where(ProviderSpend.id == reservation).values(**values)
                )
                session.commit()
        except Exception as error:  # noqa: BLE001
            logger.warning("provider spending not corrected (%s)", type(error).__name__)


def _reserve(session: Session, model: str, cost: int) -> uuid.UUID:
    settings = get_settings()
    limits = (
        ("daily", timedelta(days=1), settings.provider_spend_limit_daily),
        ("monthly", timedelta(days=30), settings.provider_spend_limit_monthly),
    )
    limit_write_time(session)
    session.execute(select(func.pg_advisory_xact_lock(_LOCK)))
    now = clock.now()
    warnings = []
    for name, window, dollars in limits:
        limit = int(dollars * NANO)
        spent = session.scalar(
            select(func.coalesce(func.sum(ProviderSpend.cost_nano_usd), 0)).where(
                ProviderSpend.created_at > now - window
            )
        )
        total = int(spent or 0) + cost
        if total > limit:
            logger.warning("provider call refused (%s spending limit)", name)
            raise ProviderBudgetError()
        if total * 100 >= limit * WARN_PERCENT:
            warnings.append((total * 100 // limit, name))
    reservation = uuid.uuid4()
    session.add(ProviderSpend(id=reservation, model=model, cost_nano_usd=cost, created_at=now))
    session.commit()
    for percent, name in warnings:
        logger.warning("provider spending is at %d%% of the %s limit", percent, name)
    return reservation
