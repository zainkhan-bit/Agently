"""The development seed script is idempotent and refuses to run in production."""

import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Membership, User, Workspace
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
def test_seed_stores_only_a_password_hash(db_session: Session) -> None:
    seed_dev.seed(db_session)
    user = db_session.scalars(select(User)).one()
    assert user.password_hash != seed_dev.DEMO_PASSWORD
    assert PasswordHasher().verify(user.password_hash, seed_dev.DEMO_PASSWORD)


def test_seed_refuses_to_run_in_production(monkeypatch) -> None:
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(get_settings(), "environment", "production")
        # If the guard failed, main() would try to open a real session; make that loud.
        monkeypatch.setattr(seed_dev, "get_session_factory", lambda: pytest.fail("touched DB"))
        assert seed_dev.main() != 0
    finally:
        get_settings.cache_clear()
