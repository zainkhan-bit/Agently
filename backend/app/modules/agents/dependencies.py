"""The only way for a request to reach an agent: through the caller's own workspace."""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.core.errors import NotFoundError, RateLimitError
from app.modules.agents.models import Agent, AgentVersion
from app.modules.identity import throttle
from app.modules.identity.dependencies import CurrentUser, Db
from app.modules.workspaces.dependencies import MemberContext, OwnerContext
from app.modules.workspaces.service import WorkspaceContext


def get_agent(agent_id: uuid.UUID, context: MemberContext, db: Db) -> Agent:
    """404 unless the agent is in this workspace, whatever else the caller belongs to."""
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.workspace_id == context.workspace.id)
    )
    if agent is None:
        raise NotFoundError()
    return agent


AgentInWorkspace = Annotated[Agent, Depends(get_agent)]


def get_version(version_id: uuid.UUID, agent: AgentInWorkspace, db: Db) -> AgentVersion:
    """404 unless the version belongs to the agent in the path."""
    version = db.scalar(
        select(AgentVersion).where(AgentVersion.id == version_id, AgentVersion.agent_id == agent.id)
    )
    if version is None:
        raise NotFoundError()
    return version


VersionOfAgent = Annotated[AgentVersion, Depends(get_version)]


def require_agent_owner(_: AgentInWorkspace, context: OwnerContext) -> WorkspaceContext:
    """The agent comes first: one from elsewhere is a 404 even for a member who gets 403 here."""
    return context


AgentOwnerContext = Annotated[WorkspaceContext, Depends(require_agent_owner)]


def _count_write(user: CurrentUser, db: Db) -> None:
    """Commits, so nothing may be locked yet."""
    if throttle.record_attempt(db, throttle.agent_write_limits(user.id)) is None:
        raise RateLimitError()


# These run after the access check they depend on and before the body is validated, so invalid
# requests count and nobody's allowance changes what an outsider sees.
def count_create(_: MemberContext, user: CurrentUser, db: Db) -> None:
    _count_write(user, db)


def count_agent_write(_: AgentInWorkspace, user: CurrentUser, db: Db) -> None:
    _count_write(user, db)


def count_version_write(_: VersionOfAgent, user: CurrentUser, db: Db) -> None:
    _count_write(user, db)
