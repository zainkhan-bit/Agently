"""The browser-check cleanup deletes only check accounts, and only on a local dev database."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Membership, User, Workspace
from scripts import delete_check_accounts as script

LOCAL = "postgresql+psycopg://u:p@localhost:5432/agently"
CHECK = "browser-check-a-1@example.com"
OTHER_CHECK = "browser-check-b-1@example.com"
LOOKALIKES = ["browser-check-1@example.com.evil.test", "x-browser-check-1@example.com"]


def add_user(session: Session, email: str) -> Workspace:
    user, workspace = User(email=email, password_hash="x"), Workspace(name=email)
    session.add_all([user, workspace])
    session.flush()
    session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    session.flush()
    return workspace


def emails(session: Session) -> set[str]:
    return set(session.scalars(select(User.email)))


def workspace_names(session: Session) -> set[str]:
    return set(session.scalars(select(Workspace.name)))


@pytest.mark.db
def test_deletes_only_the_named_account_and_its_workspace(db_session: Session) -> None:
    for email in (CHECK, OTHER_CHECK, "real@example.com", *LOOKALIKES):
        add_user(db_session, email)
    assert script.delete_accounts(db_session, [CHECK, "real@example.com"]) == 1
    kept = {OTHER_CHECK, "real@example.com", *LOOKALIKES}
    assert emails(db_session) == workspace_names(db_session) == kept


@pytest.mark.db
def test_all_deletes_every_check_account_and_nothing_else(db_session: Session) -> None:
    for email in (CHECK, OTHER_CHECK, "real@example.com", *LOOKALIKES):
        add_user(db_session, email)
    assert script.delete_accounts(db_session, None) == 2
    assert emails(db_session) == workspace_names(db_session) == {"real@example.com", *LOOKALIKES}


@pytest.mark.db
def test_a_shared_workspace_stops_the_whole_deletion(db_session: Session) -> None:
    shared = add_user(db_session, CHECK)
    add_user(db_session, "real@example.com")
    real = db_session.scalars(select(User).where(User.email == "real@example.com")).one()
    db_session.add(Membership(user_id=real.id, workspace_id=shared.id, role="member"))
    db_session.flush()
    with pytest.raises(ValueError, match="not being deleted"):
        script.delete_accounts(db_session, None)
    assert emails(db_session) == {CHECK, "real@example.com"}


@pytest.mark.parametrize(
    ("environment", "url"),
    [
        ("production", LOCAL),
        ("test", LOCAL),
        ("development", LOCAL.replace("localhost", "db.example.com")),
        ("development", ""),
    ],
)
def test_refuses_without_connecting(environment: str, url: str, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(script, "get_session_factory", lambda: pytest.fail("touched DB"))
    get_settings.cache_clear()
    try:
        assert script.main(["--all"]) == 1
    finally:
        get_settings.cache_clear()
    assert "Refusing" in capsys.readouterr().err


@pytest.mark.parametrize("args", [[], ["real@example.com"], [CHECK, "--all"], [LOOKALIKES[0]]])
def test_refuses_other_arguments_without_connecting(args: list[str], monkeypatch) -> None:
    monkeypatch.setattr(script, "get_session_factory", lambda: pytest.fail("touched DB"))
    assert script.main(args) == 2
