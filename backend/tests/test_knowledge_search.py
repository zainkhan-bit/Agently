"""Searching an agent's knowledge over HTTP: who may search, the limits, what is never logged.

The whole app runs against the test database, so these prove the route's access checks, limits
and logging, and that its results come only from the agent in the path. Ranking and matching are
proven on the retriever itself in test_retrieval.py.
"""

# The imported fixtures are used as arguments.
# ruff: noqa: F401, F811

import logging
import uuid

import pytest

from app.models import Agent, AuthThrottleEvent, Workspace
from app.modules.knowledge import retrieval
from tests.test_agents_api import code, count, create, s
from tests.test_conversations import c
from tests.test_retrieval import REFUND, source

pytestmark = pytest.mark.db

QUESTION = "refund purchase secret-question-7d1e"


def url(c, agent=None) -> str:
    return f"{c.url}/{agent or c.agent}/knowledge/search"


def ask(client, target, question=QUESTION, **body):
    return client.post(target, json={"question": question, **body})


def agent_row(db, c, agent=None) -> Agent:
    return db.get(Agent, uuid.UUID(str(agent or c.agent)))


@pytest.mark.parametrize("role", ["owner", "member"])
def test_members_get_excerpts_in_rank_order(c, db_session, role) -> None:
    other = "A refund needs the receipt."
    found = source(db_session, agent_row(db_session, c), other, REFUND, name="policy.txt")
    response = ask(getattr(c, role), url(c))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {
                "source_id": str(found.id),
                "source_name": "policy.txt",
                "page": None,
                "sequence": 1,
                "text": REFUND,
            },
            {
                "source_id": str(found.id),
                "source_name": "policy.txt",
                "page": None,
                "sequence": 0,
                "text": other,
            },
        ]
    }
    assert response.headers["cache-control"] == "private, no-store"


def test_results_come_only_from_the_agent_in_the_path(c, db_session) -> None:
    sibling = create(c.owner, c.url)["id"]
    stranger_home = Workspace(name="elsewhere")
    db_session.add(stranger_home)
    db_session.flush()
    stranger = Agent(workspace_id=stranger_home.id, status="active", current_version=1)
    db_session.add(stranger)
    db_session.flush()
    mine = source(db_session, agent_row(db_session, c), REFUND, name="mine.txt")
    source(db_session, agent_row(db_session, c, sibling), REFUND, name="sibling.txt")
    source(db_session, stranger, REFUND, name="stranger.txt")

    response = ask(c.member, url(c), "refund")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [(i["source_id"], i["source_name"]) for i in items] == [(str(mine.id), "mine.txt")]
    assert "sibling.txt" not in response.text and "stranger.txt" not in response.text


def test_an_outsider_gets_404_and_counts_nothing(c, db_session) -> None:
    source(db_session, agent_row(db_session, c), REFUND)
    before = count(db_session, AuthThrottleEvent)
    response = ask(c.outsider, url(c))
    assert response.status_code == 404
    assert REFUND not in response.text
    assert count(db_session, AuthThrottleEvent) == before


def test_signed_out_gets_401(c, make_client) -> None:
    assert ask(make_client(), url(c)).status_code == 401


def test_a_get_is_not_served(c) -> None:
    assert c.member.get(url(c), params={"question": "refund"}).status_code == 405


@pytest.mark.parametrize(
    "body",
    [
        {"question": "x" * 501},
        {"question": "refund", "limit": 0},
        {"question": "refund", "limit": 11},
        {"question": ""},
        {"question": "   \n\t "},
        {},
        {"question": 5},
    ],
)
def test_requests_beyond_the_limits_are_refused_before_searching(c, monkeypatch, body) -> None:
    def never(*args, **kwargs):
        raise AssertionError("searched")

    monkeypatch.setattr(retrieval.FullTextRetriever, "search", never)
    response = c.member.post(url(c), json=body)
    assert response.status_code == 422
    assert code(response) == "validation_error"


def test_a_lower_configured_question_limit_is_enforced(c, configure) -> None:
    configure(knowledge_search_question_max_chars=50)
    fifty = "refund " + "x" * 43
    assert ask(c.member, url(c), fifty).status_code == 200
    assert ask(c.member, url(c), fifty + "y").status_code == 422


def test_without_a_count_the_default_applies(c, db_session, configure) -> None:
    configure(knowledge_search_default_results=2)
    source(db_session, agent_row(db_session, c), *[f"refund note {n}" for n in range(5)])
    assert len(ask(c.member, url(c), "refund").json()["items"]) == 2
    assert len(ask(c.member, url(c), "refund", limit=4).json()["items"]) == 4


def test_the_sixty_first_search_in_ten_minutes_is_refused(c, configure) -> None:
    configure(knowledge_search_limit_per_user=60, knowledge_search_window_minutes=10)
    for _ in range(60):
        assert ask(c.member, url(c), "refund").status_code == 200
    refused = ask(c.member, url(c), "refund")
    assert refused.status_code == 429
    assert code(refused) == "rate_limited"
    # Per person: a teammate can still search.
    assert ask(c.owner, url(c), "refund").status_code == 200


def test_questions_and_excerpts_are_never_logged(c, db_session, configure, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    source(db_session, agent_row(db_session, c), REFUND)
    assert ask(c.member, url(c)).status_code == 200
    assert ask(c.member, url(c), QUESTION + " " + "x" * 500).status_code == 422
    configure(knowledge_search_limit_per_user=1)
    ask(c.member, url(c))
    assert ask(c.member, url(c)).status_code == 429
    logged = "\n".join(record.getMessage() for record in caplog.records)
    logged += "\n".join(str(record.args) for record in caplog.records)
    assert "secret-question-7d1e" not in logged
    assert "Refunds are accepted" not in logged
