"""The database itself enforces identity and tenancy rules."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Agent, AgentVersion, Membership, User, UserSession, Workspace

pytestmark = pytest.mark.db


def make_user(session: Session, email: str = "alice@example.com") -> User:
    user = User(email=email, password_hash="argon2-hash-placeholder")
    session.add(user)
    session.flush()
    return user


def make_workspace(session: Session, name: str = "Acme") -> Workspace:
    workspace = Workspace(name=name)
    session.add(workspace)
    session.flush()
    return workspace


def make_session(session: Session, user: User, token_hash: str = "a" * 64) -> UserSession:
    row = UserSession(
        user_id=user.id, token_hash=token_hash, expires_at=datetime.now(UTC) + timedelta(days=1)
    )
    session.add(row)
    session.flush()
    return row


def count(session: Session, model, *where) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))


def test_database_generates_uuid_and_timezone_aware_timestamps(db_session: Session) -> None:
    db_session.execute(User.__table__.insert().values(email="raw@example.com", password_hash="h"))
    row = db_session.execute(
        select(User.__table__).where(User.__table__.c.email == "raw@example.com")
    ).one()
    assert isinstance(row.id, uuid.UUID)
    assert row.created_at.tzinfo is not None
    assert row.updated_at.tzinfo is not None


def test_email_unique_regardless_of_case(db_session: Session) -> None:
    make_user(db_session, "alice@example.com")
    with pytest.raises(IntegrityError, match="uq_users_email_lower"):
        make_user(db_session, "Alice@Example.com")


def test_membership_unique_per_user_and_workspace(db_session: Session) -> None:
    user = make_user(db_session)
    first, second = make_workspace(db_session, "One"), make_workspace(db_session, "Two")
    db_session.add(Membership(user_id=user.id, workspace_id=first.id, role="owner"))
    db_session.add(Membership(user_id=user.id, workspace_id=second.id, role="member"))
    db_session.flush()  # one user can belong to many workspaces

    db_session.add(Membership(user_id=user.id, workspace_id=first.id, role="member"))
    with pytest.raises(IntegrityError, match="uq_memberships_user_id_workspace_id"):
        db_session.flush()


@pytest.mark.parametrize("role", ["admin", "", "Owner"])
def test_membership_role_must_be_owner_or_member(db_session: Session, role: str) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    db_session.add(Membership(user_id=user.id, workspace_id=workspace.id, role=role))
    with pytest.raises(IntegrityError, match="ck_memberships_role_valid"):
        db_session.flush()


def test_membership_rejects_unknown_user(db_session: Session) -> None:
    workspace = make_workspace(db_session)
    db_session.add(Membership(user_id=uuid.uuid4(), workspace_id=workspace.id, role="member"))
    with pytest.raises(IntegrityError, match="fk_memberships_user_id_users"):
        db_session.flush()


def test_membership_rejects_unknown_workspace(db_session: Session) -> None:
    user = make_user(db_session)
    db_session.add(Membership(user_id=user.id, workspace_id=uuid.uuid4(), role="member"))
    with pytest.raises(IntegrityError, match="fk_memberships_workspace_id_workspaces"):
        db_session.flush()


def make_agent(session: Session, workspace: Workspace, user: User) -> Agent:
    agent = Agent(workspace_id=workspace.id, status="active", current_version=1, created_by=user.id)
    session.add(agent)
    session.flush()
    session.add(make_version(agent, user))
    session.flush()
    return agent


def make_version(agent: Agent, user: User, number: int = 1) -> AgentVersion:
    return AgentVersion(
        agent_id=agent.id, number=number, name="A", instructions="I", created_by=user.id
    )


@pytest.mark.parametrize("status", ["draft", "", "Active"])
def test_agent_status_must_be_known(db_session: Session, status: str) -> None:
    workspace = make_workspace(db_session)
    db_session.add(Agent(workspace_id=workspace.id, status=status, current_version=1))
    with pytest.raises(IntegrityError, match="ck_agents_status_valid"):
        db_session.flush()


def test_agent_version_numbers_are_unique_and_positive(db_session: Session) -> None:
    user = make_user(db_session)
    agent = make_agent(db_session, make_workspace(db_session), user)
    with pytest.raises(IntegrityError, match="uq_agent_versions_agent_id_number"):
        with db_session.begin_nested():
            db_session.add(make_version(agent, user))
    with pytest.raises(IntegrityError, match="ck_agent_versions_number_positive"):
        with db_session.begin_nested():
            db_session.add(make_version(agent, user, 0))


def test_a_version_can_only_come_from_an_earlier_one_of_its_own_agent(
    db_session: Session,
) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    agent, other = (make_agent(db_session, workspace, user) for _ in range(2))
    db_session.add(make_version(other, user, 2))
    db_session.flush()

    def add(number: int, source: int) -> None:
        version = make_version(agent, user, number)
        version.restored_from = source
        with db_session.begin_nested():
            db_session.add(version)

    with pytest.raises(IntegrityError, match="ck_agent_versions_restored_from_earlier"):
        add(2, 2)
    with pytest.raises(IntegrityError, match="fk_agent_versions_agent_id_restored_from"):
        add(4, 2)  # the other agent has a version 2, this one does not
    add(2, 1)
    db_session.execute(delete(Agent).where(Agent.id == agent.id))
    assert count(db_session, AgentVersion) == 2


@pytest.mark.parametrize("parent", ["agent", "workspace"])
def test_deleting_an_agent_or_its_workspace_removes_versions(
    db_session: Session, parent: str
) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    agent = make_agent(db_session, workspace, user)
    model, key = (Agent, agent.id) if parent == "agent" else (Workspace, workspace.id)
    db_session.execute(delete(model).where(model.id == key))
    assert count(db_session, Agent) == count(db_session, AgentVersion) == 0


def test_deleting_the_creator_keeps_agents_and_versions(db_session: Session) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    make_agent(db_session, workspace, user)
    db_session.execute(delete(User).where(User.id == user.id))
    assert count(db_session, Agent, Agent.created_by.is_(None)) == 1
    assert count(db_session, AgentVersion, AgentVersion.created_by.is_(None)) == 1


def test_session_rejects_unknown_user(db_session: Session) -> None:
    db_session.add(
        UserSession(user_id=uuid.uuid4(), token_hash="b" * 64, expires_at=datetime.now(UTC))
    )
    with pytest.raises(IntegrityError, match="fk_sessions_user_id_users"):
        db_session.flush()


def test_session_token_hash_unique(db_session: Session) -> None:
    user = make_user(db_session)
    make_session(db_session, user, token_hash="c" * 64)
    with pytest.raises(IntegrityError, match="uq_sessions_token_hash"):
        make_session(db_session, user, token_hash="c" * 64)


def test_session_requires_expiry_and_allows_null_revocation(db_session: Session) -> None:
    user = make_user(db_session)
    row = make_session(db_session, user)
    assert row.revoked_at is None

    db_session.add(UserSession(user_id=user.id, token_hash="d" * 64, expires_at=None))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_workspace_removes_memberships_keeps_users(db_session: Session) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    db_session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    db_session.flush()

    db_session.execute(delete(Workspace).where(Workspace.id == workspace.id))

    assert count(db_session, Membership, Membership.workspace_id == workspace.id) == 0
    assert count(db_session, User, User.id == user.id) == 1


def test_deleting_user_removes_sessions_and_memberships_keeps_workspace(
    db_session: Session,
) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    db_session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    make_session(db_session, user)

    db_session.execute(delete(User).where(User.id == user.id))

    assert count(db_session, UserSession, UserSession.user_id == user.id) == 0
    assert count(db_session, Membership, Membership.user_id == user.id) == 0
    assert count(db_session, Workspace, Workspace.id == workspace.id) == 1
