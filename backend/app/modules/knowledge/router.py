"""Knowledge sources under /api/workspaces/{workspace_id}/agents/{agent_id}/sources.

An upload is the file itself as the request body, with its name percent-encoded in the
``X-File-Name`` header: not in the URL, which access logs print. The body is counted while it is
read, so nothing larger than the limit is ever stored, and no form parser keeps an unchecked copy.
There is no route that returns a file.

Search lives under /api/workspaces/{workspace_id}/agents/{agent_id}/knowledge/search: a POST, so
that the question stays out of the URL. Questions and excerpts are never logged.
"""

import logging
import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, Query, Request, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import AppError, RateLimitError
from app.modules.agents.dependencies import AgentInWorkspace
from app.modules.conversations.dependencies import never_cached
from app.modules.identity import throttle
from app.modules.identity.dependencies import CurrentUser, Db
from app.modules.knowledge import filetypes, retrieval, service, storage
from app.modules.knowledge.models import KnowledgeSource
from app.modules.knowledge.schemas import (
    ExcerptOut,
    SearchRequest,
    SearchResults,
    SourceOut,
    SourcePage,
)
from app.modules.workspaces.dependencies import MemberContext

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/agents/{agent_id}/sources",
    tags=["knowledge"],
    dependencies=[Depends(never_cached)],
)


search_router = APIRouter(
    prefix="/workspaces/{workspace_id}/agents/{agent_id}/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(never_cached)],
)


class LengthRequiredError(AppError):
    status_code = 411
    code = "length_required"
    message = "The upload must state its size."


class UploadLimitError(RateLimitError):
    message = "You or your workspace added too many files. Please try again later."


def _out(source: KnowledgeSource) -> SourceOut:
    return SourceOut.model_validate(source, from_attributes=True)


def count_upload(_: AgentInWorkspace, context: MemberContext, user: CurrentUser, db: Db) -> None:
    """After the access check, so that outsiders count nothing. Refused uploads count. Commits."""
    if throttle.record_attempt(db, throttle.upload_limits(user.id, context.workspace.id)) is None:
        raise UploadLimitError()
    # Ends the count's transaction: reading a slow body must not keep a pooled connection.
    db.commit()


class SearchLimitError(RateLimitError):
    message = "You searched too often. Please try again in a few minutes."


def count_search(_: AgentInWorkspace, user: CurrentUser, db: Db) -> None:
    """After the access check, so that outsiders count nothing. A request with an invalid body
    still counts: validation runs after the dependencies."""
    if throttle.record_attempt(db, throttle.search_limits(user.id)) is None:
        raise SearchLimitError()


def get_source(
    source_id: uuid.UUID, agent: AgentInWorkspace, context: MemberContext, db: Db
) -> KnowledgeSource:
    """404 unless the source belongs to the agent in the path, in the workspace in the path."""
    return service.get_source(db, context, agent.id, source_id)


SourceOfAgent = Annotated[KnowledgeSource, Depends(get_source)]


# The app refuses bodies over 64 KB; this route allows up to the largest limit the settings accept,
# and _receive enforces the one configured.
UPLOAD_BODY_CEILING = 100_000_000


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(count_upload)],
    max_body_size=UPLOAD_BODY_CEILING,
)
async def upload_source(
    request: Request,
    agent: AgentInWorkspace,
    context: MemberContext,
    db: Db,
    file_name: Annotated[str, Header(alias="X-File-Name", min_length=1, max_length=3000)],
) -> SourceOut:
    """The body is the file. ``Content-Type`` is its type, ``X-File-Name`` its name."""
    try:
        name = unquote(file_name, errors="strict")
    except UnicodeDecodeError:
        raise filetypes.FileNameInvalidError() from None
    incoming = await _receive(request, get_settings().knowledge_max_file_bytes)
    source = await run_in_threadpool(
        service.add_source,
        db,
        context,
        agent.id,
        name=name,
        content_type=request.headers.get("content-type"),
        incoming=incoming,
    )
    return _out(source)


@router.get("")
def list_sources(
    agent: AgentInWorkspace,
    context: MemberContext,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> SourcePage:
    rows, total = service.list_sources(db, context, agent.id, limit=limit, offset=offset)
    return SourcePage(items=[_out(row) for row in rows], total=total)


@router.get("/{source_id}")
def read_source(source: SourceOfAgent) -> SourceOut:
    return _out(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source: SourceOfAgent, agent: AgentInWorkspace, context: MemberContext, db: Db
) -> None:
    service.delete_source(db, context, agent.id, source.id)


@search_router.post("/search", dependencies=[Depends(count_search)])
def search(body: SearchRequest, agent: AgentInWorkspace, db: Db) -> SearchResults:
    """Excerpts of the agent's ready documents, best first."""
    limit = body.limit or get_settings().knowledge_search_default_results
    found = retrieval.get_retriever().search(db, agent.workspace_id, agent.id, body.question, limit)
    return SearchResults(
        items=[ExcerptOut.model_validate(excerpt, from_attributes=True) for excerpt in found]
    )


async def _receive(request: Request, maximum: int) -> Path:
    """The body in a new private file, refused as soon as it is too large."""
    declared = request.headers.get("content-length")
    if declared is None or not declared.isdigit():
        raise LengthRequiredError()
    if int(declared) == 0:
        raise filetypes.FileEmptyError()
    if int(declared) > maximum:
        logger.warning("knowledge file refused (%s)", filetypes.FileTooLargeError.code)
        raise filetypes.FileTooLargeError()
    path = await run_in_threadpool(storage.incoming_path)
    received = 0
    try:
        with path.open("wb") as file:
            async for chunk in request.stream():
                received += len(chunk)
                if received > maximum:
                    raise filetypes.FileTooLargeError()
                file.write(chunk)
        if received != int(declared):
            raise filetypes.FileMalformedError()
    except filetypes.FileRefusedError as error:
        storage.discard(path)
        logger.warning("knowledge file refused (%s)", error.code)
        raise
    except BaseException:
        storage.discard(path)
        raise
    return path
