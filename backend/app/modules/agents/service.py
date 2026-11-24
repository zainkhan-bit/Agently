"""Agent rules.

Every write locks the workspace, then the caller's membership, then the agent, and decides from
the locked rows. What the request saw when it started is not trusted.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import Row, delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.text import NAME_MAX
from app.modules.agents.models import ACTIVE, ARCHIVED, PAUSED, Agent, AgentVersion
from app.modules.workspaces.service import (
    WorkspaceContext,
    lock_for_member_write,
    lock_owners_as_owner,
)

MAX_VERSIONS = 200

# action: (allowed from, result)
TRANSITIONS = {
    "pause": ({ACTIVE}, PAUSED),
    "resume": ({PAUSED}, ACTIVE),
    "archive": ({ACTIVE, PAUSED}, ARCHIVED),
    "restore": ({ARCHIVED}, PAUSED),
}

CONFIGURATION = ("name", "purpose", "description", "instructions", "model")

AgentWithVersion = tuple[Agent, AgentVersion]


class AgentLimitError(ConflictError):
    code = "agent_limit"


class VersionLimitError(ConflictError):
    code = "version_limit"
    message = f"This agent already has {MAX_VERSIONS} saved versions. No more can be saved."


class VersionConflictError(ConflictError):
    code = "version_conflict"
    message = "This agent has changed since you opened it. Reload it and try again."


class AgentPausedError(ConflictError):
    code = "agent_paused"
    message = "This agent is paused."


class AgentArchivedError(ConflictError):
    code = "agent_archived"
    message = "This agent is archived. Restore it first."


class StatusConflictError(ConflictError):
    code = "status_conflict"


def ensure_can_run(agent: Agent) -> None:
    """The one rule for whether an agent may run. Phase 3 must call it before every run."""
    if agent.status == ARCHIVED:
        raise AgentArchivedError()
    if agent.status != ACTIVE:
        raise AgentPausedError()


def list_agents(
    db: Session, context: WorkspaceContext, *, archived: bool, limit: int, offset: int
) -> tuple[Sequence[Row[AgentWithVersion]], int]:
    where = (
        Agent.workspace_id == context.workspace.id,
        Agent.status == ARCHIVED if archived else Agent.status != ARCHIVED,
    )
    rows = db.execute(
        _with_version()
        .where(*where)
        .order_by(Agent.created_at.desc(), Agent.id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count()).select_from(Agent).where(*where)) or 0
    return rows, total


def read_agent(db: Session, context: WorkspaceContext, agent_id: uuid.UUID) -> AgentWithVersion:
    row = db.execute(
        _with_version()
        .where(Agent.id == agent_id, Agent.workspace_id == context.workspace.id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise NotFoundError()
    return row[0], row[1]


def create_agent(
    db: Session, context: WorkspaceContext, configuration: dict[str, str | None]
) -> AgentWithVersion:
    lock_for_member_write(db, context)
    created = _add_agent(db, context, ACTIVE, configuration)
    db.commit()
    return created


def update_agent(
    db: Session,
    context: WorkspaceContext,
    agent_id: uuid.UUID,
    version: int,
    changes: dict[str, str | None],
) -> AgentWithVersion:
    agent = _lock_agent(db, context, agent_id)
    if agent.status == ARCHIVED:
        raise AgentArchivedError()
    if agent.current_version != version:
        raise VersionConflictError(details={"current_version": agent.current_version})
    current = _current_version(db, agent)
    before = _configuration(current)
    after = before | changes
    if after == before:
        db.commit()  # or the locks would last until the response has been sent
        return agent, current
    if agent.current_version >= MAX_VERSIONS:
        raise VersionLimitError()
    agent.current_version += 1
    saved = _add_version(db, context, agent, after)
    db.commit()
    return agent, saved


def duplicate_agent(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID
) -> AgentWithVersion:
    source = _lock_agent(db, context, agent_id)
    configuration = _configuration(_current_version(db, source))
    configuration["name"] = f"Copy of {configuration['name']}"[:NAME_MAX].rstrip()
    created = _add_agent(db, context, PAUSED, configuration)
    db.commit()
    return created


def change_status(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, action: str
) -> AgentWithVersion:
    agent = _lock_agent(db, context, agent_id)
    allowed, result = TRANSITIONS[action]
    if agent.status not in allowed:
        raise StatusConflictError(f"Cannot {action} an agent that is {agent.status}.")
    agent.status = result
    db.flush()
    current = _current_version(db, agent)
    db.commit()
    return agent, current


def delete_agent(db: Session, context: WorkspaceContext, agent_id: uuid.UUID) -> None:
    """Delete permanently. The database cascades to everything the agent owns (ADR-0005)."""
    lock_owners_as_owner(db, context)
    deleted = db.execute(
        delete(Agent)
        .where(Agent.id == agent_id, Agent.workspace_id == context.workspace.id)
        .execution_options(synchronize_session=False)
    )
    if deleted.rowcount == 0:
        raise NotFoundError()
    db.commit()


def _with_version():
    return select(Agent, AgentVersion).join(
        AgentVersion,
        (AgentVersion.agent_id == Agent.id) & (AgentVersion.number == Agent.current_version),
    )


def _lock_agent(db: Session, context: WorkspaceContext, agent_id: uuid.UUID) -> Agent:
    lock_for_member_write(db, context)
    agent = db.scalar(
        select(Agent)
        .where(Agent.id == agent_id, Agent.workspace_id == context.workspace.id)
        .with_for_update()
        # The request already loaded this agent; without this it would keep those old values.
        .execution_options(populate_existing=True)
    )
    if agent is None:
        raise NotFoundError()
    return agent


def _current_version(db: Session, agent: Agent) -> AgentVersion:
    return db.scalars(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.number == agent.current_version
        )
    ).one()


def _configuration(version: AgentVersion) -> dict[str, str | None]:
    return {field: getattr(version, field) for field in CONFIGURATION}


def _add_agent(
    db: Session, context: WorkspaceContext, status: str, configuration: dict[str, str | None]
) -> AgentWithVersion:
    """The workspace lock must be held, so that parallel requests count in turn."""
    limit = get_settings().agent_limit_per_workspace
    count = db.scalar(
        select(func.count()).select_from(Agent).where(Agent.workspace_id == context.workspace.id)
    )
    if (count or 0) >= limit:
        raise AgentLimitError(f"A workspace can have at most {limit} agents, archived included.")
    agent = Agent(
        workspace_id=context.workspace.id,
        status=status,
        current_version=1,
        created_by=context.user_id,
    )
    db.add(agent)
    db.flush()
    return agent, _add_version(db, context, agent, configuration)


def _add_version(
    db: Session, context: WorkspaceContext, agent: Agent, configuration: dict[str, str | None]
) -> AgentVersion:
    version = AgentVersion(
        agent_id=agent.id,
        number=agent.current_version,
        created_by=context.user_id,
        **configuration,
    )
    db.add(version)
    db.flush()
    return version
