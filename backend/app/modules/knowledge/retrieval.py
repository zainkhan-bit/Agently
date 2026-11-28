"""Retrieval: the excerpts of one agent's ready documents that best answer a question.

Callers use only ``get_retriever()`` and ``Excerpt``, so what sits behind them can change without
touching any caller: PostgreSQL full-text search now, embeddings with pgvector later (ADR-0007).
Results come in rank order and carry no score, because the scores of different implementations
are on different scales and must not be compared or used as thresholds.

Questions and excerpts are private: nothing here logs them.
"""

import unicodedata
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings


@dataclass(frozen=True)
class Excerpt:
    source_id: uuid.UUID
    source_name: str
    page: int | None  # PDFs only
    sequence: int  # the chunk's position in its source
    text: str


class Retriever(Protocol):
    def search(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        question: str,
        limit: int,
    ) -> list[Excerpt]:
        """At most ``limit`` excerpts, best first, from the agent's ready sources only."""
        ...


def words(question: str) -> list[str]:
    """Runs of letters, combining marks and digits, in any script. Never punctuation or
    symbols, so no search operator can get through. Marks count as part of a word, or Hindi
    and decomposed accents ("café") would fall apart into single letters."""
    found: list[str] = []
    current: list[str] = []
    for character in question:
        if unicodedata.category(character)[0] in "LMN":
            current.append(character)
        elif current:
            found.append("".join(current))
            current = []
    if current:
        found.append("".join(current))
    return found


# PostgreSQL's English configuration drops stop words; 'simple' keeps every word. So the
# exact-word query is built only from the words English does not drop, or "the and of" would
# match nearly everything. "or" is an English stop word, so no query word is ever an operator.
_MEANINGFUL = text(
    "SELECT word FROM unnest(CAST(:words AS text[])) WITH ORDINALITY AS t(word, n) "
    "WHERE to_tsvector('english'::regconfig, word) <> ''::tsvector ORDER BY n"
)

# The search, run once per pass. The workspace, agent and ready-status filters are always applied.
# It is filled in twice below: every word (plainto_tsquery) and any word (websearch_to_tsquery
# over "a or b").
_SEARCH_SQL = """
WITH q AS (
    SELECT {english} AS english, {simple} AS simple
)
SELECT c.id, c.source_id, s.name, c.page, c.sequence, c.content
FROM knowledge_chunks AS c
JOIN knowledge_sources AS s ON s.id = c.source_id
CROSS JOIN q
WHERE c.workspace_id = :workspace_id
  AND c.agent_id = :agent_id
  AND s.status = 'ready'
  AND (c.search_english @@ q.english OR c.search_simple @@ q.simple)
  AND NOT (c.id = ANY(CAST(:exclude AS uuid[])))
ORDER BY GREATEST(ts_rank_cd(c.search_english, q.english), ts_rank_cd(c.search_simple, q.simple))
         DESC, c.source_id, c.sequence
LIMIT :limit
"""
_EVERY_WORD = text(
    _SEARCH_SQL.format(
        english="plainto_tsquery('english'::regconfig, :question)",
        simple="plainto_tsquery('simple'::regconfig, :exact)",
    )
)
_ANY_WORD = text(
    _SEARCH_SQL.format(
        english="websearch_to_tsquery('english'::regconfig, :any)",
        simple="websearch_to_tsquery('simple'::regconfig, :any)",
    )
)


class FullTextRetriever:
    def search(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        question: str,
        limit: int,
    ) -> list[Excerpt]:
        settings = get_settings()
        limit = min(limit, settings.knowledge_search_max_results)
        if limit <= 0:
            return []
        # PostgreSQL compares lexemes as stored bytes; documents are almost always composed (NFC).
        question = unicodedata.normalize("NFC", question)
        meaningful = list(db.scalars(_MEANINGFUL, {"words": words(question)}))
        if not meaningful:
            return []  # only stop words or punctuation: no query could match anything real
        scope = {"workspace_id": workspace_id, "agent_id": agent_id}
        rows = list(
            db.execute(
                _EVERY_WORD,
                {
                    **scope,
                    "question": question,
                    "exact": " ".join(meaningful),
                    "exclude": [],
                    "limit": limit,
                },
            )
        )
        if len(rows) < limit:
            rows += db.execute(
                _ANY_WORD,
                {
                    **scope,
                    "any": " or ".join(meaningful),
                    "exclude": [row.id for row in rows],
                    "limit": limit - len(rows),
                },
            )
        cut = settings.knowledge_search_excerpt_max_chars
        return [
            Excerpt(row.source_id, row.name, row.page, row.sequence, row.content[:cut])
            for row in rows
        ]


def get_retriever() -> Retriever:
    """The one way callers obtain a retriever: replacing the implementation changes only this."""
    return FullTextRetriever()
