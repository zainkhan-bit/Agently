"""Knowledge source rules. Sources belong to an agent and are shared by the workspace's members.

A file is checked completely before its record is written, and the record is committed before the
file is reachable by its final name. Deleting removes the record first and the file after the
commit, so a failure can only leave a file without a record, which the sweep removes.
"""

import hashlib
import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.modules.agents.models import ARCHIVED
from app.modules.agents.service import AgentArchivedError, lock_agent
from app.modules.knowledge import filetypes, storage
from app.modules.knowledge.models import PENDING, KnowledgeSource
from app.modules.workspaces.models import Workspace
from app.modules.workspaces.service import WorkspaceContext

logger = logging.getLogger(__name__)


class StorageLimitError(ConflictError):
    code = "storage_limit"
    message = "This workspace has no room for this file. Delete other sources first."


class SourceLimitError(ConflictError):
    code = "source_limit"
    message = "This agent has too many sources. Delete one first."


class SourceDuplicateError(ConflictError):
    code = "source_duplicate"
    message = "This agent already has a source with exactly this content."


def add_source(
    db: Session,
    context: WorkspaceContext,
    agent_id: uuid.UUID,
    *,
    name: str,
    content_type: str | None,
    incoming: Path,
) -> KnowledgeSource:
    """Check the received file and keep it. Commits. The incoming file is gone afterwards."""
    try:
        shown, kind = filetypes.check_name(name)
        filetypes.check_declared(kind, content_type)
        filetypes.check_content(incoming, kind)
        size = incoming.stat().st_size
        digest = _sha256(incoming)
        source = _record(db, context, agent_id, shown, kind, size, digest)
        storage.place(incoming, source.storage_name)
        try:
            db.commit()
        except BaseException:
            storage.discard(storage.path_of(source.storage_name))
            raise
        return source
    except filetypes.FileRefusedError as error:
        logger.warning("knowledge file refused (%s)", error.code)
        raise
    finally:
        storage.discard(incoming)


def _record(
    db: Session,
    context: WorkspaceContext,
    agent_id: uuid.UUID,
    name: str,
    kind: str,
    size: int,
    digest: str,
) -> KnowledgeSource:
    agent = lock_agent(db, context, agent_id)
    if agent.status == ARCHIVED:
        raise AgentArchivedError()
    # Uploads to one workspace take turns, so that two cannot both fit into the last room.
    db.execute(
        select(Workspace.id)
        .where(Workspace.id == context.workspace.id)
        .with_for_update(key_share=True)
    )
    settings = get_settings()
    used = db.scalar(
        select(func.coalesce(func.sum(KnowledgeSource.size_bytes), 0)).where(
            KnowledgeSource.workspace_id == context.workspace.id
        )
    )
    if used + size > settings.knowledge_storage_limit_per_workspace_bytes:
        raise StorageLimitError()
    count = db.scalar(
        select(func.count())
        .select_from(KnowledgeSource)
        .where(KnowledgeSource.agent_id == agent.id)
    )
    if count >= settings.knowledge_sources_per_agent:
        raise SourceLimitError()
    duplicate = db.scalar(
        select(KnowledgeSource.id).where(
            KnowledgeSource.agent_id == agent.id, KnowledgeSource.sha256 == digest
        )
    )
    if duplicate is not None:
        raise SourceDuplicateError()
    source = KnowledgeSource(
        workspace_id=context.workspace.id,
        agent_id=agent.id,
        uploaded_by=context.user_id,
        name=name,
        kind=kind,
        size_bytes=size,
        sha256=digest,
        storage_name=storage.new_name(),
        status=PENDING,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    db.add(source)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise SourceDuplicateError() from None
    return source


def list_sources(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[Sequence[KnowledgeSource], int]:
    where = _of_agent(context, agent_id)
    rows = db.scalars(
        select(KnowledgeSource)
        .where(*where)
        .order_by(KnowledgeSource.created_at.desc(), KnowledgeSource.id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count()).select_from(KnowledgeSource).where(*where)) or 0
    return rows, total


def get_source(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, source_id: uuid.UUID
) -> KnowledgeSource:
    source = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id, *_of_agent(context, agent_id)
        )
    )
    if source is None:
        raise NotFoundError()
    return source


def delete_source(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, source_id: uuid.UUID
) -> None:
    """Also when the agent is paused or archived."""
    lock_agent(db, context, agent_id)
    storage_name = db.scalar(
        delete(KnowledgeSource)
        .where(KnowledgeSource.id == source_id, *_of_agent(context, agent_id))
        .returning(KnowledgeSource.storage_name)
    )
    if storage_name is None:
        raise NotFoundError()
    db.commit()
    storage.remove([storage_name])


def _of_agent(context: WorkspaceContext, agent_id: uuid.UUID):
    return (
        KnowledgeSource.workspace_id == context.workspace.id,
        KnowledgeSource.agent_id == agent_id,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
