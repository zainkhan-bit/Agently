"""Agent rules.

Every write locks the workspace, then the caller's membership, then the agent, and decides from
the locked rows. What the request saw when it started is not trusted.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Row, delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.text import NAME_MAX
from app.modules.agents.models import ACTIVE, ARCHIVED, PAUSED, Agent, AgentVersion
from app.modules.agents.schemas import AgentCreate
from app.modules.identity.models import User
from app.modules.knowledge import storage as knowledge_storage
from app.modules.workspaces.models import Membership
from app.modules.workspaces.service import (
    WorkspaceContext,
    lock_for_member_write,
    lock_owners_as_owner,
)

MAX_VERSIONS = 200
VERSION_PAGE = 20

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
    message = (
        f"This agent already has {MAX_VERSIONS} saved versions, so no more can be saved. "
        "Duplicate the agent to continue with a new history."
    )


class VersionInvalidError(ConflictError):
    code = "version_invalid"
    message = "This version no longer meets the rules for agents, so it cannot be restored."


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


def ensure_room(db: Session, context: WorkspaceContext) -> None:
    """Only an early answer unless the workspace lock is held."""
    limit = get_settings().agent_limit_per_workspace
    count = db.scalar(
        select(func.count()).select_from(Agent).where(Agent.workspace_id == context.workspace.id)
    )
    if (count or 0) >= limit:
        raise AgentLimitError(f"A workspace can have at most {limit} agents, archived included.")


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
    agent = _lock_for_save(db, context, agent_id, version)
    current = _current_version(db, agent)
    return _save(db, context, agent, current, _configuration(current) | changes)


def roll_back(
    db: Session,
    context: WorkspaceContext,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    version: int,
) -> AgentWithVersion:
    """Save a new version copied from an earlier one. ``version`` is the current one as seen."""
    agent = _lock_for_save(db, context, agent_id, version)
    source = db.scalar(
        select(AgentVersion).where(AgentVersion.id == version_id, AgentVersion.agent_id == agent.id)
    )
    if source is None:
        raise NotFoundError()
    current = _current_version(db, agent)
    return _save(db, context, agent, current, _configuration(source), source.number)


def duplicate_agent(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID
) -> AgentWithVersion:
    source = lock_agent(db, context, agent_id)
    configuration = _configuration(_current_version(db, source))
    configuration["name"] = f"Copy of {configuration['name']}"[:NAME_MAX].rstrip()
    created = _add_agent(db, context, PAUSED, configuration)
    db.commit()
    return created


def change_status(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, action: str
) -> AgentWithVersion:
    agent = lock_agent(db, context, agent_id)
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
    files = knowledge_storage.files_of(db, agent_id=agent_id)
    deleted = db.execute(
        delete(Agent)
        .where(Agent.id == agent_id, Agent.workspace_id == context.workspace.id)
        .execution_options(synchronize_session=False)
    )
    if deleted.rowcount == 0:
        raise NotFoundError()
    db.commit()
    knowledge_storage.remove(files)  # after the commit: a file can outlive its record, not reverse


@dataclass(frozen=True)
class VersionEntry:
    version: AgentVersion
    is_current: bool
    changed: list[str] | None
    saved_by: str | None


def list_versions(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, before: int | None
) -> tuple[list[VersionEntry], int | None]:
    """One page, newest first, and where the next one starts."""
    query = (
        _versions(context, agent_id)
        .add_columns(Agent.current_version)
        .order_by(AgentVersion.number.desc())
        .limit(VERSION_PAGE + 1)  # the last entry is compared with the one after it
    )
    if before is not None:
        query = query.where(AgentVersion.number < before)
    rows = db.execute(query).all()
    if not rows and before is None:
        raise NotFoundError()  # an agent always has a version: it has just been deleted
    entries = []
    for index, (version, saved_by, current) in enumerate(rows[:VERSION_PAGE]):
        changed = None
        if index + 1 < len(rows):
            old, new = _configuration(rows[index + 1][0]), _configuration(version)
            changed = [field for field in CONFIGURATION if new[field] != old[field]]
        entries.append(VersionEntry(version, version.number == current, changed, saved_by))
    return entries, entries[-1].version.number if len(rows) > VERSION_PAGE else None


def read_version(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[AgentVersion, str | None]:
    row = db.execute(
        _versions(context, agent_id).where(AgentVersion.id == version_id)
    ).one_or_none()
    if row is None:
        raise NotFoundError()
    return row[0], row[1]


def _versions(context: WorkspaceContext, agent_id: uuid.UUID):
    """Versions with the saver's email, which is empty unless they are a member now."""
    return (
        select(AgentVersion, User.email)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .outerjoin(
            Membership,
            (Membership.user_id == AgentVersion.created_by)
            & (Membership.workspace_id == Agent.workspace_id),
        )
        .outerjoin(User, User.id == Membership.user_id)
        .where(Agent.id == agent_id, Agent.workspace_id == context.workspace.id)
    )


def _with_version():
    return select(Agent, AgentVersion).join(
        AgentVersion,
        (AgentVersion.agent_id == Agent.id) & (AgentVersion.number == Agent.current_version),
    )


def lock_agent(db: Session, context: WorkspaceContext, agent_id: uuid.UUID) -> Agent:
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


def _lock_for_save(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, version: int
) -> Agent:
    agent = lock_agent(db, context, agent_id)
    if agent.status == ARCHIVED:
        raise AgentArchivedError()
    if agent.current_version != version:
        raise VersionConflictError(details={"current_version": agent.current_version})
    return agent


def _save(
    db: Session,
    context: WorkspaceContext,
    agent: Agent,
    current: AgentVersion,
    configuration: dict[str, str | None],
    restored_from: int | None = None,
) -> AgentWithVersion:
    """Add a version and commit, unless nothing changes. The agent must be locked."""
    if configuration == _configuration(current):
        db.commit()  # or the locks would last until the response has been sent
        return agent, current
    if agent.current_version >= MAX_VERSIONS:
        raise VersionLimitError()
    if restored_from is not None and not _meets_rules(configuration):
        raise VersionInvalidError()
    agent.current_version += 1
    saved = _add_version(db, context, agent, configuration, restored_from)
    db.commit()
    return agent, saved


def _meets_rules(configuration: dict[str, str | None]) -> bool:
    """Old versions may predate a rule. Edits have already been checked by their schema."""
    try:
        # Also the same after cleaning up, because the stored text itself is copied.
        return AgentCreate.model_validate(configuration).model_dump() == configuration
    except ValidationError:
        return False


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
    ensure_room(db, context)
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
    db: Session,
    context: WorkspaceContext,
    agent: Agent,
    configuration: dict[str, str | None],
    restored_from: int | None = None,
) -> AgentVersion:
    version = AgentVersion(
        agent_id=agent.id,
        number=agent.current_version,
        restored_from=restored_from,
        created_by=context.user_id,
        **configuration,
    )
    db.add(version)
    db.flush()
    return version
