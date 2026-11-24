"""Agent endpoints under /api/workspaces/{workspace_id}/agents."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.modules.agents import service
from app.modules.agents.dependencies import (
    AgentInWorkspace,
    AgentOwnerContext,
    count_agent_write,
    count_create,
)
from app.modules.agents.models import Agent, AgentVersion
from app.modules.agents.schemas import AgentCreate, AgentOut, AgentPage, AgentSummary, AgentUpdate
from app.modules.identity.dependencies import Db
from app.modules.workspaces.dependencies import MemberContext

router = APIRouter(prefix="/workspaces/{workspace_id}/agents", tags=["agents"])


def _summary(agent: Agent, version: AgentVersion) -> AgentSummary:
    return AgentSummary(
        id=agent.id,
        workspace_id=agent.workspace_id,
        status=agent.status,
        version=version.number,
        name=version.name,
        purpose=version.purpose,
        description=version.description,
        model=version.model,
        created_by=agent.created_by,
        version_created_by=version.created_by,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _out(agent: Agent, version: AgentVersion) -> AgentOut:
    return AgentOut(**_summary(agent, version).model_dump(), instructions=version.instructions)


@router.get("")
def list_agents(
    context: MemberContext,
    db: Db,
    archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> AgentPage:
    rows, total = service.list_agents(db, context, archived=archived, limit=limit, offset=offset)
    return AgentPage(items=[_summary(agent, version) for agent, version in rows], total=total)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(count_create)])
def create_agent(body: AgentCreate, context: MemberContext, db: Db) -> AgentOut:
    return _out(*service.create_agent(db, context, body.model_dump()))


@router.get("/{agent_id}")
def get_agent(agent: AgentInWorkspace, context: MemberContext, db: Db) -> AgentOut:
    return _out(*service.read_agent(db, context, agent.id))


@router.patch("/{agent_id}", dependencies=[Depends(count_agent_write)])
def update_agent(
    agent: AgentInWorkspace, body: AgentUpdate, context: MemberContext, db: Db
) -> AgentOut:
    return _out(*service.update_agent(db, context, agent.id, body.version, body.changes()))


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent: AgentInWorkspace, context: AgentOwnerContext, db: Db) -> None:
    service.delete_agent(db, context, agent.id)


@router.post(
    "/{agent_id}/duplicate",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(count_agent_write)],
)
def duplicate_agent(agent: AgentInWorkspace, context: MemberContext, db: Db) -> AgentOut:
    return _out(*service.duplicate_agent(db, context, agent.id))


@router.post("/{agent_id}/pause")
def pause_agent(agent: AgentInWorkspace, context: MemberContext, db: Db) -> AgentOut:
    return _out(*service.change_status(db, context, agent.id, "pause"))


@router.post("/{agent_id}/resume")
def resume_agent(agent: AgentInWorkspace, context: MemberContext, db: Db) -> AgentOut:
    return _out(*service.change_status(db, context, agent.id, "resume"))


@router.post("/{agent_id}/archive")
def archive_agent(agent: AgentInWorkspace, context: MemberContext, db: Db) -> AgentOut:
    return _out(*service.change_status(db, context, agent.id, "archive"))


@router.post("/{agent_id}/restore")
def restore_agent(agent: AgentInWorkspace, context: MemberContext, db: Db) -> AgentOut:
    return _out(*service.change_status(db, context, agent.id, "restore"))
