"""Private file storage for knowledge sources.

Files are named by 32 random hex characters, never by anything a person chose, and the name is
checked again before any path is built from it. The folder is outside anything that is served.
Nothing here logs a file's name or content.
"""

import logging
import os
import re
import secrets
import time
import uuid
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.knowledge.models import KnowledgeSource

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPOSITORY = BACKEND_DIR.parent
# Inside the repository only here: it is ignored by git. Anywhere else in it, files could be
# served, run, or committed to a public repository.
ALLOWED_IN_REPOSITORY = BACKEND_DIR / "var"
INCOMING = "incoming"
NAME = re.compile(r"[0-9a-f]{32}")
ORPHAN_AGE_SECONDS = 3600


def root() -> Path:
    configured = get_settings().knowledge_storage_dir
    folder = Path(configured) if configured else BACKEND_DIR / "var" / "knowledge"
    folder = (folder if folder.is_absolute() else BACKEND_DIR / folder).resolve()
    inside = REPOSITORY.resolve() in (folder, *folder.parents)
    allowed = ALLOWED_IN_REPOSITORY.resolve() in folder.parents
    if inside and not allowed:
        raise RuntimeError("KNOWLEDGE_STORAGE_DIR must be outside the repository or in backend/var")
    (folder / INCOMING).mkdir(parents=True, exist_ok=True)
    return folder


def new_name() -> str:
    return secrets.token_hex(16)


def path_of(storage_name: str) -> Path:
    if not NAME.fullmatch(storage_name):
        raise ValueError("not a storage name")
    return root() / storage_name


def incoming_path() -> Path:
    """A new, empty, private file that only this request writes to."""
    path = root() / INCOMING / new_name()
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
    )
    os.close(descriptor)
    return path


def place(incoming: Path, storage_name: str) -> Path:
    """Move a checked file to its final name. Fails rather than replace another file."""
    target = path_of(storage_name)
    if target.exists():
        raise FileExistsError("storage name taken")
    os.replace(incoming, target)
    return target


def discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        logger.warning("knowledge file not removed (%s)", type(error).__name__)


def remove(storage_names: Iterable[str]) -> None:
    """Best effort: a file left behind has no record, and the sweep removes it later."""
    for storage_name in storage_names:
        discard(path_of(storage_name))


def files_of(
    db: Session, *, agent_id: uuid.UUID | None = None, workspace_id: uuid.UUID | None = None
) -> list[str]:
    """Stored names to remove once the deletion of their agent or workspace is committed."""
    column = KnowledgeSource.agent_id if agent_id is not None else KnowledgeSource.workspace_id
    return list(
        db.scalars(select(KnowledgeSource.storage_name).where(column == (agent_id or workspace_id)))
    )


def sweep(db: Session, *, older_than_seconds: float = ORPHAN_AGE_SECONDS) -> int:
    """Remove files that have no record and are old enough not to be an upload in progress."""
    folder = root()
    cutoff = time.time() - older_than_seconds
    candidates = [
        path
        for path in [*folder.iterdir(), *(folder / INCOMING).iterdir()]
        if path.is_file() and NAME.fullmatch(path.name) and path.stat().st_mtime < cutoff
    ]
    known = set(
        db.scalars(
            select(KnowledgeSource.storage_name).where(
                KnowledgeSource.storage_name.in_([path.name for path in candidates])
            )
        )
    )
    removed = 0
    for path in candidates:
        if path.parent.name == INCOMING or path.name not in known:
            discard(path)
            removed += 1
    return removed
