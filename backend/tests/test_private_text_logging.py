"""Message text must never reach a log: not on a crash, not through PostgreSQL's error details."""

# The imported fixture is used as an argument.
# ruff: noqa: F811

import logging
import traceback
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core import database
from app.core.config import get_settings
from app.core.logs import configure_logging
from app.models import StoredMessage, Workspace
from app.modules.conversations import service
from app.modules.workspaces.service import WorkspaceContext
from tests.auth_helpers import ORIGIN
from tests.test_agents_api import create, s  # noqa: F401

pytestmark = pytest.mark.db

SECRET = "my private diagnosis"


@pytest.fixture
def log_levels():
    """configure_logging changes loggers for the whole process."""
    root = logging.getLogger()
    names = ("sqlalchemy", "sqlalchemy.engine", "psycopg")
    before = root.level, {name: logging.getLogger(name).level for name in names}
    yield
    root.setLevel(before[0])
    for name, level in before[1].items():
        logging.getLogger(name).setLevel(level)


@pytest.fixture
def production_engine(test_engine, monkeypatch):
    """The engine as the server builds it, on the throwaway database."""
    monkeypatch.setenv("DATABASE_URL", test_engine.url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    database.get_engine.cache_clear()
    engine = database.get_engine()
    yield engine
    engine.dispose()
    database.get_engine.cache_clear()
    get_settings.cache_clear()


def broken_message(**values) -> StoredMessage:
    """Refused by the database. Every one of these errors has a detail with the row or its key."""
    return StoredMessage(
        **{
            "conversation_id": uuid.uuid4(),
            "agent_id": uuid.uuid4(),
            "sequence": 1,
            "role": "user",
            "content": SECRET,
        }
        | values
    )


@pytest.mark.parametrize(
    "values", [{"sequence": 0}, {"role": SECRET[:20]}, {"agent_version": 1}, {"agent_id": None}, {}]
)
def test_a_rejected_message_is_not_in_the_error_or_the_log(
    production_engine, caplog, values
) -> None:
    caplog.set_level(logging.DEBUG)
    with Session(production_engine) as session:
        session.add(broken_message(**values))
        with pytest.raises(DBAPIError) as caught:
            session.flush()
    logging.getLogger("uvicorn.error").error("Exception in ASGI application", exc_info=caught.value)
    logging.getLogger("uvicorn.error").error("%s %r", caught.value, caught.value.orig)
    for text in (caplog.text, "".join(traceback.format_exception(caught.value))):
        assert SECRET[:20] not in text
    assert "violates" in caplog.text  # what went wrong is still known
    assert caught.value.orig.sqlstate


def test_a_crash_while_storing_over_http_logs_no_text(
    auth_app, s, db_session, monkeypatch, caplog
) -> None:
    agent = create(s.owner, s.url)["id"]
    url = f"{s.url}/{agent}/conversations"
    one = f"{url}/{s.owner.post(url).json()['id']}"

    def crash(db, *args, **kwargs):
        db.add(broken_message(sequence=0))
        db.flush()

    monkeypatch.setattr(service, "list_messages", crash)
    caplog.set_level(logging.DEBUG)
    client = TestClient(
        auth_app,
        base_url="https://testserver",
        raise_server_exceptions=False,
        headers={"Origin": ORIGIN},
        cookies=s.owner.cookies,
    )
    response = client.get(f"{one}/messages")
    assert response.status_code == 500
    assert "unhandled error" in caplog.text
    assert SECRET not in caplog.text and SECRET not in response.text


def test_debug_logging_shows_no_rows(database_url, log_levels, caplog) -> None:
    """hide_parameters hides parameters only: SQLAlchemy logs whole result rows at DEBUG."""
    for name in ("sqlalchemy", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    configure_logging("DEBUG")
    caplog.set_level(logging.DEBUG)
    engine = create_engine(database_url, hide_parameters=True)  # reads the levels when created
    try:
        with engine.connect() as connection:
            assert connection.scalar(select(func.concat("row: ", SECRET)))
    finally:
        engine.dispose()
    assert SECRET not in caplog.text
    for name in ("sqlalchemy.engine.Engine", "sqlalchemy.pool", "psycopg.pq"):
        assert not logging.getLogger(name).isEnabledFor(logging.INFO)


def test_a_message_never_shows_its_text_in_its_representation() -> None:
    assert SECRET not in repr(broken_message())


def test_a_refused_message_says_nothing_about_its_text(s, db_session, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    agent = uuid.UUID(create(s.owner, s.url)["id"])
    conversation = uuid.UUID(s.owner.post(f"{s.url}/{agent}/conversations").json()["id"])
    workspace = db_session.get(Workspace, uuid.UUID(s.workspace))
    context = WorkspaceContext(workspace=workspace, user_id=uuid.UUID(s.owner_id), role="owner")
    with pytest.raises(service.MessageInvalidError) as caught:
        service.store_message(
            db_session, context, agent, conversation, role="user", content=SECRET + "\x00"
        )
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text
