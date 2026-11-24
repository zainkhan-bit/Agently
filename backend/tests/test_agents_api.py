"""Agent operations, rules and limits over HTTP."""

import json
import uuid

import pytest
from sqlalchemy import func, select

from app.models import Agent, AgentVersion, AuthThrottleEvent, Membership
from app.modules.agents import service
from tests.auth_helpers import register

pytestmark = pytest.mark.db

BODY = {"name": "Helper", "instructions": "Be kind."}
ACTIONS = ("pause", "resume", "archive", "restore")


class Setup:
    pass


@pytest.fixture
def s(make_client, db_session) -> Setup:
    """An owner and a member of one workspace, and an outsider."""
    s = Setup()
    s.owner, s.member, s.outsider = make_client(), make_client(), make_client()
    s.owner_id = register(s.owner, email="owner@example.com").json()["id"]
    s.member_id = register(s.member, email="member@example.com").json()["id"]
    register(s.outsider, email="outsider@example.com")
    s.workspace = s.owner.get("/api/workspaces").json()[0]["id"]
    db_session.add(
        Membership(
            user_id=uuid.UUID(s.member_id), workspace_id=uuid.UUID(s.workspace), role="member"
        )
    )
    db_session.commit()
    s.url = f"/api/workspaces/{s.workspace}/agents"
    return s


def create(client, url, **fields) -> dict:
    response = client.post(url, json=BODY | fields)
    assert response.status_code == 201, response.text
    return response.json()


def code(response) -> str:
    return response.json()["error"]["code"]


def count(session, model, *where) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))


@pytest.mark.parametrize("role", ["owner", "member"])
def test_members_and_owners_can_manage_agents(s, role) -> None:
    client = getattr(s, role)
    agent = create(client, s.url, purpose=" Help ", description="  ")
    assert (agent["status"], agent["version"], agent["model"]) == ("active", 1, None)
    assert (agent["purpose"], agent["description"]) == ("Help", None)
    creator = getattr(s, f"{role}_id")
    assert agent["created_by"] == agent["version_created_by"] == creator
    one = f"{s.url}/{agent['id']}"
    assert client.get(one).json() == agent
    edited = client.patch(one, json={"version": 1, "name": "Renamed"}).json()
    assert (edited["name"], edited["version"]) == ("Renamed", 2)
    assert (edited["instructions"], edited["purpose"]) == ("Be kind.", "Help")
    assert client.get(one).json() == edited
    for action, status in (
        ("pause", "paused"),
        ("resume", "active"),
        ("archive", "archived"),
        ("restore", "paused"),
    ):
        assert client.post(f"{one}/{action}").json()["status"] == status
    assert client.get(one).json()["version"] == 2  # status changes save no version
    page = client.get(s.url).json()
    assert page["total"] == 1 and "instructions" not in page["items"][0]


def test_only_owners_delete(s, db_session) -> None:
    one = f"{s.url}/{create(s.member, s.url)['id']}"
    refused = s.member.delete(one)
    assert (refused.status_code, code(refused)) == (403, "permission_denied")
    assert s.member.get(one).status_code == 200
    assert s.outsider.delete(one).status_code == 404
    assert s.owner.delete(one).status_code == 204
    assert s.owner.get(one).status_code == s.owner.delete(one).status_code == 404
    assert count(db_session, AgentVersion) == 0


@pytest.mark.parametrize("status", ["paused", "archived"])
def test_delete_works_in_any_status(s, status) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    s.owner.post(f"{one}/{'pause' if status == 'paused' else 'archive'}")
    assert s.owner.delete(one).status_code == 204


def test_member_deleting_an_agent_from_elsewhere_gets_404_not_403(s) -> None:
    elsewhere = s.outsider.get("/api/workspaces").json()[0]["id"]
    theirs = create(s.outsider, f"/api/workspaces/{elsewhere}/agents")["id"]
    assert s.member.delete(f"{s.url}/{theirs}").status_code == 404
    assert s.member.delete(f"{s.url}/{uuid.uuid4()}").status_code == 404


def test_outsider_gets_404_whatever_they_send(s, configure, db_session) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    configure(agent_write_limit=1)
    own = s.outsider.get("/api/workspaces").json()[0]["id"]
    create(s.outsider, f"/api/workspaces/{own}/agents")
    used_up = s.outsider.post(f"/api/workspaces/{own}/agents", json=BODY)
    assert (used_up.status_code, code(used_up)) == (429, "rate_limited")
    for body in ({"version": 99}, {"version": 1, "name": ""}, {"nonsense": 1}, BODY):
        assert s.outsider.patch(one, json=body).status_code == 404
        assert s.outsider.post(s.url, json=body).status_code == 404
        assert s.outsider.post(f"{one}/duplicate", json=body).status_code == 404


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("name", "   "),
        ("name", "x" * 101),
        ("name", "a\u202eb"),
        ("name", None),
        ("instructions", ""),
        ("instructions", " \n\t "),
        ("instructions", "\u200b\u00a0"),
        ("instructions", "x" * 10_001),
        ("instructions", "a\x00b"),
        ("instructions", "a\x1bb"),
        ("instructions", None),
        ("instructions", 5),
        ("purpose", "x" * 501),
        ("purpose", "a\x00b"),
        ("description", "x" * 1001),
        ("description", "a\x00b"),
        ("model", "gpt"),
        ("model", ""),
        ("model", {}),
        ("workspace_id", str(uuid.uuid4())),
        ("status", "active"),
        ("created_by", str(uuid.uuid4())),
        ("current_version", 5),
        ("number", 5),
    ],
)
def test_invalid_fields_are_refused(s, db_session, field, value) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    for response in (
        s.owner.post(s.url, json=BODY | {field: value}),
        s.owner.patch(one, json={"version": 1, field: value}),
    ):
        assert response.status_code == 422
        assert field in response.json()["error"]["details"][0]["loc"]
    assert (count(db_session, Agent), count(db_session, AgentVersion)) == (1, 1)


def test_lone_surrogates_are_refused(s) -> None:
    headers = {"Content-Type": "application/json"}
    for field in ("name", "instructions", "purpose"):
        body = json.dumps(BODY | {field: "a\ud800"})
        response = s.owner.post(s.url, content=body, headers=headers)
        assert response.status_code == 422, field


def test_create_needs_a_name_and_instructions(s) -> None:
    response = s.owner.post(s.url, json={})
    assert response.status_code == 422
    assert {d["loc"][-1] for d in response.json()["error"]["details"]} == {"name", "instructions"}


@pytest.mark.parametrize("version", [None, 0, -1, "1", 1.5, True])
def test_edit_needs_a_whole_version_number(s, version) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    assert s.owner.patch(one, json={"version": version, "name": "N"}).status_code == 422
    assert s.owner.patch(one, json={"name": "N"}).status_code == 422


def test_values_at_the_limits_are_kept(s) -> None:
    fields = {
        "name": "n" * 100,
        "purpose": "p" * 500,
        "description": "d" * 1000,
        "instructions": "line\r\n\ttab " + "\U0001f600" * 9_989,
        "model": None,
    }
    assert len(fields["instructions"]) == 10_000
    agent = create(s.owner, s.url, **fields)
    assert {field: agent[field] for field in fields} == fields
    exact = create(s.owner, s.url, instructions="x" * 10_000)
    assert len(exact["instructions"]) == 10_000


def test_names_need_not_be_unique(s) -> None:
    assert create(s.owner, s.url)["id"] != create(s.owner, s.url)["id"]


@pytest.mark.parametrize("status", ["active", "paused", "archived"])
@pytest.mark.parametrize("action", ACTIONS)
def test_only_the_allowed_status_changes_happen(s, status, action) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    if status != "active":
        s.owner.post(f"{one}/{'pause' if status == 'paused' else 'archive'}")
    allowed = {
        ("active", "pause"): "paused",
        ("paused", "resume"): "active",
        ("active", "archive"): "archived",
        ("paused", "archive"): "archived",
        ("archived", "restore"): "paused",
    }
    response = s.owner.post(f"{one}/{action}")
    if (status, action) in allowed:
        assert response.json()["status"] == allowed[status, action]
    else:
        assert (response.status_code, code(response)) == (409, "status_conflict")
    assert s.owner.get(one).json()["status"] == allowed.get((status, action), status)


def test_archived_agents_are_read_only_and_leave_the_list(s) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    s.owner.post(f"{one}/archive")
    for body in ({"version": 1, "name": "N"}, {"version": 1}):
        refused = s.owner.patch(one, json=body)
        assert (refused.status_code, code(refused)) == (409, "agent_archived")
    assert s.owner.get(s.url).json() == {"items": [], "total": 0}
    assert s.owner.get(f"{s.url}?archived=true").json()["total"] == 1
    assert s.owner.get(one).json()["name"] == "Helper"
    assert s.owner.post(f"{one}/duplicate").json()["status"] == "paused"


def test_every_saved_version_is_kept_unchanged(s, db_session) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    s.member.patch(one, json={"version": 1, "instructions": "Second."})
    s.owner.patch(one, json={"version": 2, "instructions": "Third."})
    db_session.expire_all()
    versions = db_session.scalars(select(AgentVersion).order_by(AgentVersion.number)).all()
    assert [(v.number, v.instructions, str(v.created_by)) for v in versions] == [
        (1, "Be kind.", s.owner_id),
        (2, "Second.", s.member_id),
        (3, "Third.", s.owner_id),
    ]
    assert s.owner.get(one).json()["created_by"] == s.owner_id


def test_outdated_edits_are_refused_even_with_identical_text(s, db_session) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    s.owner.patch(one, json={"version": 1, "name": "Second"})
    for body in ({"version": 1, "name": "Second"}, {"version": 1}, {"version": 3, "name": "X"}):
        response = s.member.patch(one, json=body)
        assert (response.status_code, code(response)) == (409, "version_conflict")
        assert response.json()["error"]["details"] == {"current_version": 2}
    assert count(db_session, AgentVersion) == 2


def test_a_save_that_changes_nothing_makes_no_version(s, db_session) -> None:
    agent = create(s.owner, s.url, purpose="P")
    one = f"{s.url}/{agent['id']}"
    for body in ({}, BODY, {"name": " Helper "}, {"purpose": "P "}, {"description": ""}):
        response = s.member.patch(one, json={"version": 1} | body)
        assert (response.status_code, response.json()) == (200, agent)
    assert count(db_session, AgentVersion) == 1
    cleared = s.owner.patch(one, json={"version": 1, "purpose": None}).json()
    assert (cleared["purpose"], cleared["version"]) == (None, 2)


def test_version_cap_refuses_changes_but_nothing_else(s, db_session) -> None:
    agent = create(s.owner, s.url)
    row = db_session.get(Agent, uuid.UUID(agent["id"]))
    for number in range(2, service.MAX_VERSIONS):
        db_session.add(
            AgentVersion(agent_id=row.id, number=number, name="Helper", instructions="Be kind.")
        )
    row.current_version = service.MAX_VERSIONS - 1
    db_session.commit()
    one = f"{s.url}/{agent['id']}"
    assert s.owner.patch(one, json={"version": 199, "name": "L"}).json()["version"] == 200
    refused = s.owner.patch(one, json={"version": 200, "name": "M"})
    assert (refused.status_code, code(refused)) == (409, "version_limit")
    assert "200" in refused.json()["error"]["message"]
    same = s.owner.patch(one, json={"version": 200, "name": "L"})
    assert (same.status_code, same.json()["version"]) == (200, 200)
    assert count(db_session, AgentVersion) == 200
    assert s.owner.post(f"{one}/pause").status_code == 200
    copy = s.owner.post(f"{one}/duplicate")
    assert (copy.status_code, copy.json()["version"]) == (201, 1)
    assert s.owner.delete(one).status_code == 204


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Helper", "Copy of Helper"),
        ("n" * 92, "Copy of " + "n" * 92),
        ("n" * 100, "Copy of " + "n" * 92),
        ("n" * 91 + " tail", "Copy of " + "n" * 91),
    ],
)
def test_duplicate_copies_only_the_current_configuration(s, name, expected) -> None:
    agent = create(s.owner, s.url, name="Old", purpose="P")
    one = f"{s.url}/{agent['id']}"
    s.owner.patch(one, json={"version": 1, "name": name})
    response = s.member.post(f"{one}/duplicate")
    copy = response.json()
    assert response.status_code == 201 and copy["id"] != agent["id"]
    assert (copy["name"], copy["status"], copy["version"]) == (expected, "paused", 1)
    assert (copy["purpose"], copy["instructions"]) == ("P", "Be kind.")
    assert copy["created_by"] == copy["version_created_by"] == s.member_id


def test_agent_cap_counts_archived_and_is_configurable(s, configure) -> None:
    configure(agent_limit_per_workspace=2)
    first = create(s.owner, s.url)["id"]
    s.owner.post(f"{s.url}/{first}/archive")
    create(s.member, s.url)
    for response in (s.owner.post(s.url, json=BODY), s.owner.post(f"{s.url}/{first}/duplicate")):
        assert (response.status_code, code(response)) == (409, "agent_limit")
        assert "at most 2" in response.json()["error"]["message"]
    configure(agent_limit_per_workspace=1)  # lowering it only blocks new agents
    assert s.owner.post(f"{s.url}/{first}/restore").status_code == 200
    s.owner.delete(f"{s.url}/{first}")
    configure(agent_limit_per_workspace=2)
    create(s.owner, s.url)


def test_default_limits() -> None:
    from app.core.config import Settings

    fields = Settings.model_fields
    assert fields["agent_limit_per_workspace"].default == 50
    assert fields["agent_write_limit"].default == 60
    assert fields["agent_write_window_minutes"].default == 10
    assert service.MAX_VERSIONS == 200


def test_write_limit_counts_invalid_requests_across_workspaces(s, configure, advance) -> None:
    configure(agent_write_limit=6)
    other = s.owner.post("/api/workspaces", json={"name": "Other"}).json()["id"]
    one = f"{s.url}/{create(s.owner, s.url)['id']}"  # 1
    assert s.owner.patch(one, json={"version": 1, "name": "N"}).status_code == 200  # 2
    assert s.owner.post(f"{one}/duplicate").status_code == 201  # 3
    assert s.owner.post(s.url, json={"name": ""}).status_code == 422  # 4
    assert s.owner.patch(one, json={"version": 1}).status_code == 409  # 5
    create(s.owner, f"/api/workspaces/{other}/agents")  # 6
    for response in (
        s.owner.post(s.url, json=BODY),
        s.owner.post(s.url, json={"name": ""}),
        s.owner.patch(one, json={"version": 2}),
        s.owner.post(f"{one}/duplicate"),
    ):
        assert (response.status_code, code(response)) == (429, "rate_limited")
    # Everything else still works, and nobody else is affected.
    for action in ACTIONS:
        assert s.owner.post(f"{one}/{action}").status_code == 200
    assert s.owner.get(one).status_code == s.owner.get(s.url).status_code == 200
    create(s.member, s.url)
    assert s.owner.delete(one).status_code == 204
    advance(minutes=10)
    create(s.owner, s.url)


def test_reads_status_changes_and_deletes_are_not_counted(s, db_session) -> None:
    one = f"{s.url}/{create(s.owner, s.url)['id']}"
    before = count(db_session, AuthThrottleEvent)
    for action in ACTIONS:
        s.owner.post(f"{one}/{action}")
    s.owner.get(one)
    s.owner.get(s.url)
    s.owner.delete(one)
    assert count(db_session, AuthThrottleEvent) == before


def test_list_is_paginated_bounded_and_stable(s) -> None:
    ids = {create(s.owner, s.url, name=f"A{n}")["id"] for n in range(5)}
    pages = [s.owner.get(f"{s.url}?limit=2&offset={offset}").json() for offset in (0, 2, 4)]
    assert [len(page["items"]) for page in pages] == [2, 2, 1]
    assert {page["total"] for page in pages} == {5}
    seen = [item["id"] for page in pages for item in page["items"]]
    assert len(seen) == 5 and set(seen) == ids
    assert [item["id"] for item in s.owner.get(s.url).json()["items"]] == seen
    for query in ("limit=0", "limit=101", "offset=-1", f"offset={2**70}", "limit=x"):
        assert s.owner.get(f"{s.url}?{query}").status_code == 422


def test_only_active_agents_may_run() -> None:
    service.ensure_can_run(Agent(status="active"))
    with pytest.raises(service.AgentPausedError, match="paused"):
        service.ensure_can_run(Agent(status="paused"))
    with pytest.raises(service.AgentArchivedError, match="archived"):
        service.ensure_can_run(Agent(status="archived"))
