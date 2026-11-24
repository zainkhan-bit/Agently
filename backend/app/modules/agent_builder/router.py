"""Draft generation under /api/workspaces/{workspace_id}/agent-builder."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.modules.agent_builder import service
from app.modules.agent_builder.schemas import Answers, BuilderStatus, DraftOut
from app.modules.identity.dependencies import Db
from app.modules.providers.selection import CurrentProvider
from app.modules.workspaces.dependencies import MemberContext

router = APIRouter(prefix="/workspaces/{workspace_id}/agent-builder", tags=["agent-builder"])


@router.get("")
def builder_status(_: MemberContext, provider: CurrentProvider) -> BuilderStatus:
    return BuilderStatus(available=provider is not None)


@router.post("/drafts")
def generate_draft(
    body: Answers, context: MemberContext, db: Db, provider: CurrentProvider
) -> DraftOut:
    """Generates and returns a draft. Nothing is saved."""
    draft = service.generate_draft(db, context, provider, body)
    return DraftOut(draft=draft, sample=get_settings().model_provider == "mock")
