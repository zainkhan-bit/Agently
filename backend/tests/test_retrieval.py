# The imported fixture is used as an argument.
# ruff: noqa: F811

"""Retrieval: which excerpts of an agent's documents answer a question, in which order.

These call the retriever on the real test database, so they prove the SQL: matching, ranking and
the workspace, agent and ready-status filters. Who may call the search endpoint is proven over
HTTP in test_knowledge_search.py and test_tenant_isolation.py.
"""

import dataclasses
import secrets
import uuid

import pytest

from app.models import Agent, KnowledgeChunk, KnowledgeSource, Workspace
from app.modules.knowledge import retrieval
from app.modules.knowledge.retrieval import Excerpt, get_retriever
from tests.auth_helpers import configure  # noqa: F401 - a fixture

pytestmark = pytest.mark.db

REFUND = "Refunds are accepted within 30 days of purchase."


def workspace(db) -> Workspace:
    found = Workspace(name="w")
    db.add(found)
    db.flush()
    return found


def agent(db, home: Workspace) -> Agent:
    found = Agent(workspace_id=home.id, status="active", current_version=1)
    db.add(found)
    db.flush()
    return found


def source(db, owner: Agent, *texts: str, status="ready", name="notes.txt", page=None):
    found = KnowledgeSource(
        workspace_id=owner.workspace_id,
        agent_id=owner.id,
        name=name,
        kind="pdf" if page else "txt",
        size_bytes=1,
        sha256=secrets.token_hex(32),
        storage_name=secrets.token_hex(16),
        status=status,
    )
    db.add(found)
    db.flush()
    for sequence, content in enumerate(texts):
        db.add(
            KnowledgeChunk(
                source_id=found.id,
                workspace_id=owner.workspace_id,
                agent_id=owner.id,
                sequence=sequence,
                page=page,
                content=content,
            )
        )
    db.flush()
    return found


def search(db, owner: Agent, question: str, limit=5, workspace_id=None) -> list[Excerpt]:
    return get_retriever().search(db, workspace_id or owner.workspace_id, owner.id, question, limit)


def texts(found: list[Excerpt]) -> list[str]:
    return [excerpt.text for excerpt in found]


@pytest.fixture(autouse=True)
def _settings(configure) -> None:
    """Known limits, whatever the developer's backend/.env says."""


@pytest.fixture
def mine(db_session) -> Agent:
    return agent(db_session, workspace(db_session))


def test_a_question_with_a_word_the_document_lacks_still_finds_it(db_session, mine) -> None:
    source(db_session, mine, REFUND, "Opening hours are nine to five.")
    assert texts(search(db_session, mine, "what is the refund window for purchases")) == [REFUND]


def test_a_chunk_with_every_word_ranks_first(db_session, mine) -> None:
    some = "The refund desk is on the first floor."
    every = "A refund for a damaged purchase is paid within a week."
    source(db_session, mine, some, every)
    assert texts(search(db_session, mine, "refund damaged purchase", limit=2)) == [every, some]


def test_roman_urdu_words_match_exactly(db_session, mine) -> None:
    urdu = "Admission fees kitni hai? Fees 5000 rupay hai."
    source(db_session, mine, urdu, REFUND)
    assert texts(search(db_session, mine, "kitni fees")) == [urdu]


def test_english_words_match_by_their_stem(db_session, mine) -> None:
    source(db_session, mine, REFUND)
    assert texts(search(db_session, mine, "refunded")) == [REFUND]


def test_other_workspaces_and_sibling_agents_are_never_searched(db_session, mine) -> None:
    sibling = agent(db_session, db_session.get(Workspace, mine.workspace_id))
    stranger = agent(db_session, workspace(db_session))
    source(db_session, sibling, REFUND)
    source(db_session, stranger, REFUND)
    assert search(db_session, mine, "refund purchase") == []
    source(db_session, mine, REFUND)
    assert texts(search(db_session, mine, "refund purchase")) == [REFUND]


def test_an_agent_named_with_the_wrong_workspace_finds_nothing(db_session, mine) -> None:
    source(db_session, mine, REFUND)
    other = workspace(db_session)
    assert search(db_session, mine, "refund", workspace_id=other.id) == []


@pytest.mark.parametrize("status", ["pending", "processing", "failed"])
def test_sources_that_are_not_ready_are_never_searched(db_session, mine, status) -> None:
    source(db_session, mine, REFUND, status=status)
    assert search(db_session, mine, "refund") == []


@pytest.mark.parametrize(
    "question",
    ['"refund" -OR (( \' ;', "refund & | ! <-> :* \\", "refund'); DROP TABLE x; --"],
)
def test_search_syntax_in_a_question_is_harmless(db_session, mine, question) -> None:
    source(db_session, mine, REFUND)
    assert texts(search(db_session, mine, question)) == [REFUND]


@pytest.mark.parametrize("question", ["the and of", "or", "OR or Or", "?!...", "   "])
def test_a_question_without_real_words_finds_nothing(db_session, mine, question) -> None:
    source(db_session, mine, "The price of the box and of the bag.", REFUND)
    assert search(db_session, mine, question) == []


def test_sharing_only_common_words_is_not_a_match(db_session, mine) -> None:
    source(db_session, mine, "What is the time? It is the hour for tea.", REFUND)
    assert texts(search(db_session, mine, "what is the refund window")) == [REFUND]


def test_a_chunk_matched_by_both_passes_appears_once(db_session, mine) -> None:
    source(db_session, mine, REFUND, "A refund needs the receipt.")
    found = search(db_session, mine, "refund purchase", limit=5)
    assert sorted(texts(found)) == sorted([REFUND, "A refund needs the receipt."])
    assert len({(e.source_id, e.sequence) for e in found}) == len(found)


def test_never_more_than_the_requested_count(db_session, mine) -> None:
    source(db_session, mine, *[f"refund note number {n}" for n in range(8)])
    assert len(search(db_session, mine, "refund", limit=3)) == 3


def test_the_order_is_the_same_every_time(db_session, mine) -> None:
    source(db_session, mine, *[f"refund note number {n}" for n in range(6)])
    first = search(db_session, mine, "refund note")
    assert search(db_session, mine, "refund note") == first


def test_long_chunks_are_cut_to_the_excerpt_limit(db_session, mine, configure) -> None:
    configure(knowledge_search_excerpt_max_chars=20)
    long = "refund " + "x" * 50
    source(db_session, mine, long, "refund short")
    found = {e.sequence: e.text for e in search(db_session, mine, "refund")}
    assert found == {0: long[:20], 1: "refund short"}


def test_each_excerpt_names_its_source_and_place(db_session, mine) -> None:
    pdf = source(db_session, mine, "intro", REFUND, name="policy.pdf", page=3)
    txt = source(db_session, mine, "Refunds by post take longer.", name="post.txt")
    found = {e.source_id: e for e in search(db_session, mine, "refunds")}
    assert found[pdf.id] == Excerpt(pdf.id, "policy.pdf", 3, 1, REFUND)
    assert found[txt.id] == Excerpt(txt.id, "post.txt", None, 0, "Refunds by post take longer.")


def test_an_excerpt_carries_no_score() -> None:
    fields = {field.name for field in dataclasses.fields(Excerpt)}
    assert fields == {"source_id", "source_name", "page", "sequence", "text"}


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("what's the refund?", ["what", "s", "the", "refund"]),
        ("fees kitni hai", ["fees", "kitni", "hai"]),
        ('"x" -OR ((y)) a_b', ["x", "OR", "y", "a", "b"]),
        ("?!... ;", []),
    ],
)
def test_questions_are_split_into_plain_words(question, expected) -> None:
    assert retrieval.words(question) == expected


def test_an_unknown_agent_finds_nothing(db_session, mine) -> None:
    source(db_session, mine, REFUND)
    assert get_retriever().search(db_session, mine.workspace_id, uuid.uuid4(), "refund", 5) == []
