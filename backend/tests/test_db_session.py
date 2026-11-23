"""Request-scoped DB sessions: no auto-commit, rollback on error, clear error if unconfigured."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core import database
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.models import Workspace

DbSession = Annotated[Session, Depends(database.get_db)]


def build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/uncommitted/{name}")
    def uncommitted(name: str, db: DbSession) -> dict:
        db.add(Workspace(name=name))
        db.flush()
        return {"ok": True}

    @app.post("/committed/{name}")
    def committed(name: str, db: DbSession) -> dict:
        db.add(Workspace(name=name))
        db.commit()
        return {"ok": True}

    @app.post("/fails/{name}")
    def fails(name: str, db: DbSession) -> dict:
        db.add(Workspace(name=name))
        db.flush()
        raise RuntimeError("boom")

    return app


@pytest.fixture
def client(test_engine, monkeypatch) -> TestClient:
    factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    yield TestClient(build_app(), raise_server_exceptions=False)
    with test_engine.begin() as connection:
        connection.execute(delete(Workspace).where(Workspace.name.like("session-test-%")))


def persisted(test_engine, name: str) -> bool:
    with test_engine.connect() as connection:
        return connection.scalar(select(Workspace.id).where(Workspace.name == name)) is not None


@pytest.mark.db
def test_request_session_does_not_commit_implicitly(client, test_engine) -> None:
    assert client.post("/uncommitted/session-test-a").status_code == 200
    assert not persisted(test_engine, "session-test-a")


@pytest.mark.db
def test_explicit_commit_persists(client, test_engine) -> None:
    assert client.post("/committed/session-test-b").status_code == 200
    assert persisted(test_engine, "session-test-b")


@pytest.mark.db
def test_error_rolls_back_and_propagates(client, test_engine) -> None:
    response = client.post("/fails/session-test-c")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert not persisted(test_engine, "session-test-c")


def test_get_db_without_database_url_raises_clear_error(monkeypatch) -> None:
    get_settings.cache_clear()
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
    try:
        monkeypatch.setattr(get_settings(), "database_url", None)
        with pytest.raises(database.DatabaseNotConfiguredError):
            next(database.get_db())
    finally:
        get_settings.cache_clear()
        database.get_engine.cache_clear()
        database.get_session_factory.cache_clear()


def test_database_errors_do_not_expose_parameters(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/agently_test")
    get_settings.cache_clear()
    database.get_engine.cache_clear()
    try:
        assert database.get_engine().hide_parameters is True
    finally:
        database.get_engine.cache_clear()
        get_settings.cache_clear()
