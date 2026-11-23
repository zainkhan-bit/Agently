"""The development seed script is idempotent and refuses to run in production."""

import pytest
from argon2 import PasswordHasher
from sqlalchemy import CheckConstraint, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Membership, User, Workspace
from app.modules.workspaces.models import ROLES
from scripts import seed_dev


def count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


@pytest.mark.db
def test_seed_is_idempotent(db_session: Session) -> None:
    seed_dev.seed(db_session)
    seed_dev.seed(db_session)

    assert count(db_session, User) == 1
    assert count(db_session, Workspace) == 1
    membership = db_session.scalars(select(Membership)).one()
    assert membership.role == "owner"


@pytest.mark.db
def test_seed_returns_a_random_password_and_stores_only_its_hash(db_session: Session) -> None:
    password = seed_dev.seed(db_session)
    user = db_session.scalars(select(User)).one()
    assert user.password_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(user.password_hash, password)
    assert seed_dev.seed(db_session) is None

    db_session.delete(user)
    db_session.flush()
    assert seed_dev.seed(db_session) not in (None, password)


def test_seed_refuses_to_run_in_production(monkeypatch, capsys) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", LOCAL.format("localhost"))  # so only this guard can fire
    # If the guard failed, main() would try to open a real session; make that loud.
    monkeypatch.setattr(seed_dev, "get_session_factory", lambda: pytest.fail("touched DB"))
    get_settings.cache_clear()
    try:
        assert seed_dev.main() != 0
    finally:
        get_settings.cache_clear()
    assert "ENVIRONMENT=production" in capsys.readouterr().err


LOCAL = "postgresql+psycopg://u:p@{}:5432/agently"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "LOCALHOST"])
def test_local_hosts_are_accepted(host: str) -> None:
    assert seed_dev.is_local_database(LOCAL.format(host))
    assert seed_dev.is_local_database(LOCAL.format(host) + "?host=127.0.0.1")


REMOTE_URLS = [
    LOCAL.format("db.example.com"),
    LOCAL.format("localhost.example.com"),
    LOCAL.format("localhost") + "?host=db.example.com",
    LOCAL.format("localhost") + "?hostaddr=203.0.113.9",
    LOCAL.format("localhost") + "?host=localhost&host=db.example.com",
    LOCAL.format("localhost") + "?host=localhost,db.example.com",
    LOCAL.format("localhost") + "?service=production",
    LOCAL.format("localhost") + "?conninfo=hostaddr%3D203.0.113.9",
    "postgresql+psycopg:///agently",
    "not a url",
]


@pytest.mark.parametrize("url", REMOTE_URLS)
def test_main_refuses_non_local_databases_without_connecting(url: str, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(seed_dev, "get_session_factory", lambda: pytest.fail("touched DB"))
    get_settings.cache_clear()
    try:
        assert seed_dev.main() != 0
    finally:
        get_settings.cache_clear()
    output = capsys.readouterr()
    assert "local" in output.err
    assert "u:p@" not in output.out + output.err


def test_role_constraint_matches_the_migrated_one() -> None:
    (check,) = [c for c in Membership.__table__.constraints if isinstance(c, CheckConstraint)]
    assert str(check.sqltext) == "role IN ('owner', 'member')"


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_libpq_redirect_variables_are_refused(name: str, monkeypatch) -> None:
    monkeypatch.setenv(name, "anything")
    assert not seed_dev.is_local_database(LOCAL.format("localhost"))


@pytest.mark.db
@pytest.mark.parametrize("role", ROLES)
def test_database_accepts_every_role(db_session: Session, role: str) -> None:
    user = User(email="role@example.com", password_hash="x")
    workspace = Workspace(name="w")
    db_session.add_all([user, workspace])
    db_session.flush()
    db_session.add(Membership(user_id=user.id, workspace_id=workspace.id, role=role))
    db_session.flush()
