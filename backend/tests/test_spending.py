"""The server-wide spending limit: reserved before, corrected after, never passed."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core import clock
from app.core.config import Settings
from app.models import ProviderSpend
from app.modules.providers.contract import (
    Completion,
    Message,
    ProviderBudgetError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusedError,
    ProviderTimeoutError,
    Role,
    TextPiece,
)
from app.modules.providers.models import GEMINI_MODELS
from app.modules.providers.spending import NANO, MeteredProvider, worst_case

LITE = GEMINI_MODELS["gemini-3.5-flash-lite"]
MESSAGES = [Message(Role.USER, "SECRET")]
TOKENS = 6_000
RESERVED = (6 + 100) * 300 + TOKENS * 2_500  # $0.0150318
REAL = 10 * 300 + 20 * 2_500


class Fake:
    def __init__(self, result=None) -> None:
        self.result = result or Completion("answer", 10, 20)
        self.calls: list[float] = []
        self.closed = 0
        self.streams: list = []  # kept, so that only close() closes them

    def complete(self, messages, *, timeout_seconds, max_output_tokens):
        self.calls.append(timeout_seconds)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def stream(self, messages, *, timeout_seconds, max_output_tokens):
        self.streams.append(self._stream(timeout_seconds))
        return self.streams[-1]

    def _stream(self, timeout_seconds):
        self.calls.append(timeout_seconds)
        try:
            yield TextPiece("ans")
            yield self.complete([], timeout_seconds=timeout_seconds, max_output_tokens=1)
        finally:
            self.closed += 1


def run(provider, timeout=20.0):
    return provider.complete(MESSAGES, timeout_seconds=timeout, max_output_tokens=TOKENS)


def stream(provider):
    return provider.stream(MESSAGES, timeout_seconds=20, max_output_tokens=TOKENS)


@pytest.fixture
def fake() -> Fake:
    return Fake()


@pytest.fixture
def sessions(test_engine, configure):
    """Real, committed transactions, as the server makes them."""
    configure()
    factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    yield factory
    with factory() as session:
        session.execute(delete(ProviderSpend))
        session.commit()


@pytest.fixture
def metered(fake, sessions) -> MeteredProvider:
    return MeteredProvider(fake, LITE, sessions)


def spend(sessions, cost: int, **ago: float) -> None:
    with sessions() as session:
        created = clock.now() - timedelta(**ago)
        session.add(ProviderSpend(model="x", cost_nano_usd=cost, created_at=created))
        session.commit()


def costs(sessions) -> list[int]:
    with sessions() as session:
        return sorted(session.scalars(select(ProviderSpend.cost_nano_usd)))


def test_the_worst_case_covers_input_output_and_thinking() -> None:
    assert worst_case(LITE, MESSAGES, TOKENS) == RESERVED
    emoji = worst_case(LITE, [Message(Role.USER, "😀")], 1)
    assert emoji == (4 + 100) * 300 + 2_500  # bytes, not characters


@pytest.mark.parametrize("tokens", [0, LITE.max_output_tokens + 1])
def test_unsupported_sizes_are_refused(tokens) -> None:
    with pytest.raises(ProviderError):
        worst_case(LITE, MESSAGES, tokens)
    with pytest.raises(ProviderError):
        worst_case(LITE, [Message(Role.USER, "x" * LITE.max_input_tokens)], 1)


def test_prices() -> None:
    """From Google's pricing page, 2026-11-25. Change only after reading it again."""
    million = 1_000_000
    assert LITE.cost(million, 0) == 30 * NANO // 100
    assert LITE.cost(0, million) == 250 * NANO // 100
    flash = GEMINI_MODELS["gemini-3.8-flash"]
    assert flash.cost(million, 0) == 150 * NANO // 100
    assert flash.cost(0, million) == 750 * NANO // 100
    assert list(GEMINI_MODELS) == [LITE.name, flash.name]


def test_default_limits() -> None:
    fields = Settings.model_fields
    assert fields["provider_spend_limit_daily"].default == 1
    assert fields["provider_spend_limit_monthly"].default == 10


db = pytest.mark.db


@db
def test_a_successful_call_is_corrected_to_its_real_cost(metered, sessions, fake) -> None:
    assert run(metered) == fake.result
    with sessions() as session:
        row = session.scalars(select(ProviderSpend)).one()
    assert (row.cost_nano_usd, row.input_tokens, row.output_tokens) == (REAL, 10, 20)
    assert row.model == LITE.name


@db
def test_the_reservation_is_committed_before_the_call(metered, sessions, fake) -> None:
    seen = []
    inner = fake.complete
    fake.complete = lambda *a, **k: (seen.append(costs(sessions)), inner(*a, **k))[1]
    run(metered)
    assert seen == [[RESERVED]]


@db
@pytest.mark.parametrize(
    "failure",
    [
        ProviderTimeoutError(),
        ProviderRateLimitError(),
        ProviderRefusedError(),
        ProviderError(),
        ValueError("x"),
        KeyboardInterrupt(),
    ],
)
@pytest.mark.parametrize("streamed", [False, True])
def test_other_failures_keep_their_reservation(metered, sessions, fake, failure, streamed) -> None:
    fake.result = failure
    with pytest.raises(type(failure)):
        list(stream(metered)) if streamed else run(metered)
    assert costs(sessions) == [RESERVED]


@db
@pytest.mark.parametrize("streamed", [False, True])
def test_an_uncharged_failure_gives_its_reservation_back(metered, sessions, fake, streamed) -> None:
    fake.result = ProviderRateLimitError(uncharged=True)
    with pytest.raises(ProviderRateLimitError):
        list(stream(metered)) if streamed else run(metered)
    assert costs(sessions) == [0] and len(fake.calls) >= 1


@db
def test_uncharged_failures_cannot_use_up_the_day(metered, sessions, fake, configure) -> None:
    configure(provider_spend_limit_daily="0.02")  # one reservation fits
    fake.result = ProviderError(uncharged=True)
    for _ in range(5):
        with pytest.raises(ProviderError) as caught:
            run(metered)
        assert type(caught.value) is ProviderError
    fake.result = ProviderError()
    with pytest.raises(ProviderError):
        run(metered)
    with pytest.raises(ProviderBudgetError):
        run(metered)


@db
def test_a_reservation_that_cannot_be_given_back_stays(fake, sessions) -> None:
    fake.result = ProviderError(uncharged=True)
    factories = iter([sessions, broken_sessions])
    with pytest.raises(ProviderError):
        run(MeteredProvider(fake, LITE, lambda: next(factories)()))
    assert costs(sessions) == [RESERVED]


@db
def test_a_reader_cannot_get_its_reservation_back(metered, sessions) -> None:
    reading = stream(metered)
    next(reading)
    with pytest.raises(ProviderError):
        reading.throw(ProviderError(uncharged=True))
    assert costs(sessions) == [RESERVED]


@db
def test_a_finished_stream_is_corrected(metered, sessions, fake) -> None:
    assert list(stream(metered)) == [TextPiece("ans"), fake.result]
    assert costs(sessions) == [REAL] and fake.closed == 1


@db
def test_a_cancelled_stream_keeps_its_reservation_and_cancels_the_call(
    metered, sessions, fake
) -> None:
    cancelled = stream(metered)
    next(cancelled)
    cancelled.close()
    assert costs(sessions) == [RESERVED] and fake.closed == 1


@db
def test_an_unread_stream_costs_nothing(metered, sessions, fake) -> None:
    stream(metered).close()
    assert costs(sessions) == [] and fake.calls == []


@db
@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize(
    ("limit", "other", "ago"),
    [
        ("provider_spend_limit_daily", "provider_spend_limit_monthly", {"hours": 23}),
        ("provider_spend_limit_monthly", "provider_spend_limit_daily", {"days": 29}),
    ],
)
def test_both_limits(metered, sessions, fake, configure, limit, other, ago, streamed) -> None:
    configure(**{limit: "0.5", other: "100"})
    spend(sessions, NANO // 2 - RESERVED + 1, **ago)
    with pytest.raises(ProviderBudgetError):
        list(stream(metered)) if streamed else run(metered)
    assert fake.calls == [] and len(costs(sessions)) == 1
    with sessions() as session:
        session.execute(delete(ProviderSpend))
        session.commit()
    spend(sessions, NANO // 2 - RESERVED, **ago)  # fits exactly
    run(metered)


@db
def test_the_windows_roll(metered, sessions, configure) -> None:
    configure(provider_spend_limit_daily="0.02", provider_spend_limit_monthly="0.04")
    spend(sessions, NANO // 50, hours=24, minutes=1)
    spend(sessions, NANO, days=30, minutes=1)
    run(metered)  # neither counts for the day, only the first for the month


@db
def test_parallel_calls_cannot_pass_the_limit_together(sessions, configure) -> None:
    room = 3
    configure(provider_spend_limit_daily=str((RESERVED * room + 1) / NANO))
    start = threading.Barrier(10)
    fake = Fake(ProviderError())

    def attempt(_) -> type:
        start.wait()
        try:
            run(MeteredProvider(fake, LITE, sessions))
        except ProviderError as error:
            return type(error)

    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(attempt, range(10)))
    assert results.count(ProviderBudgetError) == 10 - room
    assert len(fake.calls) == room and costs(sessions) == [RESERVED] * room


@db
def test_a_warning_at_eighty_percent_of_either_limit(metered, sessions, configure, caplog) -> None:
    def warned(daily: str, monthly: str, spent: int) -> list[str]:
        configure(provider_spend_limit_daily=daily, provider_spend_limit_monthly=monthly)
        with sessions() as session:
            session.execute(delete(ProviderSpend))
            session.commit()
        spend(sessions, spent)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            run(metered)
        return [r.getMessage() for r in caplog.records if r.name.startswith("app.")]

    edge = NANO * 8 // 10 - RESERVED
    assert warned("1", "100", edge - 1) == []
    assert warned("1", "100", edge) == ["provider spending is at 80% of the daily limit"]
    assert warned("100", "1", edge) == ["provider spending is at 80% of the monthly limit"]
    assert len(warned("1", "1", edge)) == 2


@db
def test_a_refusal_is_logged_without_private_text(metered, sessions, configure, caplog) -> None:
    configure(provider_spend_limit_daily="0.01")
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderBudgetError):
        run(metered)
    assert "provider call refused (daily spending limit)" in caplog.text
    assert "SECRET" not in caplog.text


def broken_sessions():
    raise RuntimeError("SECRET")


def test_no_record_means_no_call(fake, configure, caplog) -> None:
    configure()
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as caught:
        run(MeteredProvider(fake, LITE, broken_sessions))
    assert type(caught.value) is ProviderError and caught.value.__context__ is None
    assert fake.calls == [] and "SECRET" not in caplog.text


@db
def test_a_failed_commit_means_no_call(fake, sessions) -> None:
    class Failing(Session):
        def commit(self) -> None:
            raise RuntimeError

    with pytest.raises(ProviderError):
        run(MeteredProvider(fake, LITE, lambda: Failing(sessions.kw["bind"])))
    assert fake.calls == [] and costs(sessions) == []


@db
def test_a_failed_correction_keeps_the_answer_and_the_reservation(fake, sessions, caplog) -> None:
    factories = iter([sessions, broken_sessions])
    provider = MeteredProvider(fake, LITE, lambda: next(factories)())
    with caplog.at_level(logging.DEBUG):
        assert run(provider) == fake.result
    assert costs(sessions) == [RESERVED]
    assert "provider spending not corrected (RuntimeError)" in caplog.text
    assert "SECRET" not in caplog.text


@db
def test_time_spent_reserving_comes_off_the_deadline(fake, sessions) -> None:
    provider = MeteredProvider(fake, LITE, sessions)
    run(provider)
    assert 0 < fake.calls[0] < 20
    with pytest.raises(ProviderTimeoutError):
        run(provider, timeout=0.000001)
    assert len(fake.calls) == 1
    assert costs(sessions) == [0, REAL]  # never sent, so given back


@db
def test_a_held_lock_refuses_the_call(metered, sessions, fake, configure) -> None:
    configure(write_lock_timeout_seconds=1)
    with sessions() as holder:
        holder.execute(select(func.pg_advisory_xact_lock(7_310_531)))
        with pytest.raises(ProviderError):
            run(metered)
    assert fake.calls == []


@db
def test_the_ledger_holds_no_text_and_no_people() -> None:
    assert set(ProviderSpend.__table__.columns.keys()) == {
        "id",
        "model",
        "cost_nano_usd",
        "input_tokens",
        "output_tokens",
        "created_at",
    }
    assert not ProviderSpend.__table__.foreign_keys
