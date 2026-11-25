"""Version history and rollback over HTTP."""

# The imported fixture is used as an argument.
# ruff: noqa: F401, F811

import logging
import uuid

import pytest
from sqlalchemy import delete, select, text

from app.models import Agent, AgentVersion, Membership, User, Workspace
from app.modules.agents import service
from app.modules.workspaces.service import WorkspaceContext
from tests.auth_helpers import register
from tests.test_agents_api import code, count, create, s

pytestmark = pytest.mark.db

CONFIGURATION = ("name", "purpose", "description", "instructions", "model")


@pytest.fixture
def v(s):
    """An agent with three versions: created, instructions changed, name and purpose changed."""
    s.one = f"{s.url}/{create(s.owner, s.url)['id']}"
    s.agent_id = uuid.UUID(s.one.rsplit("/", 1)[1])
    edit(s.member, s.one, 1, instructions="Be brief.")
    edit(s.owner, s.one, 2, name="Renamed", purpose="Support")
    return s


def edit(client, one, version, **fields) -> dict:
    response = client.patch(one, json={"version": version} | fields)
    assert response.status_code == 200, response.text
    return response.json()


def history(client, one, **query) -> dict:
    response = client.get(f"{one}/versions", params=query)
    assert response.status_code == 200, response.text
    return response.json()


def version_url(client, one, number) -> str:
    page = history(client, one, before=number + 1)
    assert page["items"][0]["number"] == number
    return f"{one}/versions/{page['items'][0]['id']}"


def roll_back(client, one, number, current):
    url = version_url(client, one, number)
    return client.post(f"{url}/rollback", json={"version": current})


def rows(session) -> list:
    """Every stored version, exactly as it is."""
    return session.execute(
        text("SELECT v::text FROM agent_versions v ORDER BY agent_id, number")
    ).all()


def fill(session, agent_id, until, **fields) -> None:
    """Add versions up to a number, all alike."""
    agent = session.get(Agent, agent_id)
    values = {"name": "Helper", "instructions": "Be kind."} | fields
    for number in range(agent.current_version + 1, until + 1):
        session.add(AgentVersion(agent_id=agent_id, number=number, **values))
    agent.current_version = until
    session.commit()


@pytest.mark.parametrize("role", ["owner", "member"])
def test_history_shows_what_changed_who_saved_and_which_is_current(v, role) -> None:
    client = getattr(v, role)
    page = history(client, v.one)
    assert [
        (i["number"], i["name"], i["changed"], i["saved_by"], i["is_current"], i["restored_from"])
        for i in page["items"]
    ] == [
        (3, "Renamed", ["name", "purpose"], "owner@example.com", True, None),
        (2, "Helper", ["instructions"], "member@example.com", False, None),
        (1, "Helper", None, "owner@example.com", False, None),
    ]
    assert page["next_before"] is None
    assert all(i["created_at"].endswith(("Z", "+00:00")) for i in page["items"])


def test_the_list_carries_no_instructions_or_user_ids(v) -> None:
    body = v.owner.get(f"{v.one}/versions").text
    assert "Be kind." not in body and "Be brief." not in body
    assert v.owner_id not in body and v.member_id not in body


def test_one_version_shows_its_whole_configuration(v) -> None:
    body = v.member.get(version_url(v.owner, v.one, 2)).json()
    assert {field: body[field] for field in CONFIGURATION} == {
        "name": "Helper",
        "purpose": None,
        "description": None,
        "instructions": "Be brief.",
        "model": None,
    }
    assert (body["number"], body["saved_by"]) == (2, "member@example.com")
    assert v.member_id not in str(body)


def test_status_changes_make_no_history_entry(v) -> None:
    v.owner.post(f"{v.one}/pause")
    assert len(history(v.owner, v.one)["items"]) == 3


def test_history_is_paged_and_compares_across_pages(v, db_session) -> None:
    fill(db_session, v.agent_id, 20)
    edit(v.owner, v.one, 20, name="N", instructions="I")
    first = history(v.owner, v.one)
    assert [i["number"] for i in first["items"]] == list(range(21, 1, -1))
    assert first["items"][0]["changed"] == ["name", "instructions"]
    # Version 2 ends the page; version 1, which it is compared with, is on the next one.
    assert first["items"][-1]["changed"] == ["instructions"]
    assert first["next_before"] == 2
    second = history(v.owner, v.one, before=2)
    assert [i["number"] for i in second["items"]] == [1]
    assert (second["items"][0]["changed"], second["next_before"]) == (None, None)


def test_exactly_one_full_page_has_no_next_page(v, db_session) -> None:
    fill(db_session, v.agent_id, 20)
    page = history(v.owner, v.one)
    assert (len(page["items"]), page["next_before"]) == (20, None)


def test_a_version_saved_while_paging_shifts_nothing(v, db_session) -> None:
    fill(db_session, v.agent_id, 25)
    first = history(v.owner, v.one)
    edit(v.owner, v.one, 25, name="Meanwhile")
    second = history(v.owner, v.one, before=first["next_before"])
    numbers = [i["number"] for i in first["items"] + second["items"]]
    assert numbers == list(range(25, 0, -1))


@pytest.mark.parametrize("before", ["0", "-1", "x", "1.5", "100001"])
def test_a_bad_page_start_is_refused(v, before) -> None:
    assert v.owner.get(f"{v.one}/versions?before={before}").status_code == 422


def test_paging_past_the_end_is_empty(v) -> None:
    assert history(v.owner, v.one, before=1) == {"items": [], "next_before": None}


def test_someone_who_left_is_not_named(v, db_session) -> None:
    url = version_url(v.owner, v.one, 2)
    mine = (
        Membership.user_id == uuid.UUID(v.member_id),
        Membership.workspace_id == uuid.UUID(v.workspace),
    )
    db_session.execute(delete(Membership).where(*mine))
    db_session.commit()
    for response in (v.owner.get(f"{v.one}/versions"), v.owner.get(url)):
        assert response.status_code == 200
        assert "member@example.com" not in response.text and v.member_id not in response.text
    assert history(v.owner, v.one)["items"][1]["saved_by"] is None
    assert v.owner.get(url).json()["saved_by"] is None
    # Someone who joins again is named again.
    db_session.add(
        Membership(
            user_id=uuid.UUID(v.member_id), workspace_id=uuid.UUID(v.workspace), role="member"
        )
    )
    db_session.commit()
    assert history(v.owner, v.one)["items"][1]["saved_by"] == "member@example.com"


def test_being_a_member_of_another_workspace_does_not_name_someone(v, db_session) -> None:
    """The member still has their own personal workspace, so they have a membership."""
    assert count(db_session, Membership, Membership.user_id == uuid.UUID(v.member_id)) == 2
    db_session.execute(
        delete(Membership).where(
            Membership.user_id == uuid.UUID(v.member_id),
            Membership.workspace_id == uuid.UUID(v.workspace),
        )
    )
    db_session.commit()
    items = history(v.owner, v.one)["items"]
    assert [i["saved_by"] for i in items] == ["owner@example.com", None, "owner@example.com"]


def test_a_deleted_account_is_not_named(v, db_session) -> None:
    db_session.execute(delete(User).where(User.id == uuid.UUID(v.member_id)))
    db_session.commit()
    assert history(v.owner, v.one)["items"][1]["saved_by"] is None


def test_members_of_two_workspaces_appear_once(v, db_session) -> None:
    """The membership join must not multiply rows."""
    assert len(v.member.get("/api/workspaces").json()) == 2
    assert [i["number"] for i in history(v.owner, v.one)["items"]] == [3, 2, 1]


@pytest.mark.parametrize("role", ["owner", "member"])
def test_rollback_saves_a_copy_and_changes_no_history(v, db_session, role) -> None:
    client = getattr(v, role)
    v.owner.post(f"{v.one}/pause")
    before = rows(db_session)
    response = roll_back(client, v.one, 1, 3)
    assert response.status_code == 200
    agent = response.json()
    assert (agent["version"], agent["status"]) == (4, "paused")
    assert agent["version_created_by"] == getattr(v, f"{role}_id")
    assert client.get(v.one).json() == agent
    assert rows(db_session)[:3] == before
    old = client.get(version_url(client, v.one, 1)).json()
    new = client.get(version_url(client, v.one, 4)).json()
    assert {f: new[f] for f in CONFIGURATION} == {f: old[f] for f in CONFIGURATION}
    assert new["id"] != old["id"]
    assert (new["restored_from"], old["restored_from"]) == (1, None)
    top = history(client, v.one)["items"][0]
    assert (top["restored_from"], top["is_current"]) == (1, True)
    assert top["changed"] == ["name", "purpose", "instructions"]


def test_every_configuration_field_is_restored(v, db_session) -> None:
    old = edit(v.owner, v.one, 3, name="A", purpose="B", description="C", instructions=" D\n")
    edit(v.owner, v.one, 4, name="W", purpose=None, description=None, instructions="Z")
    assert roll_back(v.owner, v.one, 4, 5).status_code == 200
    now = v.owner.get(v.one).json()
    assert {f: now[f] for f in CONFIGURATION} == {f: old[f] for f in CONFIGURATION}
    assert (now["instructions"], now["version"]) == (" D\n", 6)


def test_only_rollbacks_record_a_source(v, db_session) -> None:
    roll_back(v.owner, v.one, 1, 3)
    copy = v.owner.post(f"{v.one}/duplicate").json()
    edit(v.owner, v.one, 4, name="Edited")
    assert [i["restored_from"] for i in history(v.owner, v.one)["items"]] == [
        None,
        1,
        None,
        None,
        None,
    ]
    assert history(v.owner, f"{v.url}/{copy['id']}")["items"][0]["restored_from"] is None


def test_a_rollback_can_itself_be_rolled_back(v) -> None:
    roll_back(v.owner, v.one, 1, 3)
    agent = roll_back(v.owner, v.one, 3, 4).json()
    assert (agent["name"], agent["version"]) == ("Renamed", 5)
    assert history(v.owner, v.one)["items"][0]["restored_from"] == 3


@pytest.mark.parametrize("seen", [1, 2, 4, 2**31])
def test_a_stale_rollback_is_refused(v, db_session, seen) -> None:
    before = rows(db_session)
    response = roll_back(v.owner, v.one, 1, seen)
    assert (response.status_code, code(response)) == (409, "version_conflict")
    assert response.json()["error"]["details"] == {"current_version": 3}
    assert rows(db_session) == before


def test_a_stale_rollback_is_refused_even_if_nothing_would_change(v) -> None:
    assert code(roll_back(v.owner, v.one, 3, 2)) == "version_conflict"


@pytest.mark.parametrize(
    "body", [None, {}, {"version": 0}, {"version": "3"}, {"version": 3, "name": "x"}]
)
def test_the_rollback_body_is_strict(v, db_session, body) -> None:
    before = rows(db_session)
    url = version_url(v.owner, v.one, 1)
    assert v.owner.post(f"{url}/rollback", json=body).status_code == 422
    assert rows(db_session) == before


def test_archived_agents_show_history_but_do_not_roll_back(v, db_session) -> None:
    v.owner.post(f"{v.one}/archive")
    before = rows(db_session)
    assert len(history(v.member, v.one)["items"]) == 3
    assert v.member.get(version_url(v.owner, v.one, 1)).status_code == 200
    response = roll_back(v.owner, v.one, 1, 3)
    assert (response.status_code, code(response)) == (409, "agent_archived")
    assert rows(db_session) == before


def test_a_rollback_that_changes_nothing_saves_nothing(v, db_session) -> None:
    assert roll_back(v.owner, v.one, 1, 3).json()["version"] == 4
    before = rows(db_session)
    updated = v.owner.get(v.one).json()["updated_at"]
    for number in (4, 1):  # the current version, and an older one that equals it
        response = roll_back(v.owner, v.one, number, 4)
        assert (response.status_code, response.json()["version"]) == (200, 4)
    assert rows(db_session) == before
    assert v.owner.get(v.one).json()["updated_at"] == updated


def test_the_version_limit_holds_for_rollback(v, db_session) -> None:
    fill(db_session, v.agent_id, service.MAX_VERSIONS - 1)
    assert roll_back(v.owner, v.one, 3, 199).json()["version"] == 200
    before = rows(db_session)
    response = roll_back(v.owner, v.one, 1, 200)
    assert (response.status_code, code(response)) == (409, "version_limit")
    message = response.json()["error"]["message"]
    assert "200" in message and "Duplicate" in message
    # Equal to the current one: nothing to save, so nothing to refuse.
    assert roll_back(v.owner, v.one, 3, 200).status_code == 200
    assert rows(db_session) == before
    edited = v.owner.patch(v.one, json={"version": 200, "name": "X"})
    assert (code(edited), "Duplicate" in edited.text) == ("version_limit", True)


@pytest.mark.parametrize(
    "broken",
    [
        {"name": "a‮b"},
        {"name": "   "},
        {"name": "\x1fAgent"},
        {"purpose": " "},
        {"instructions": " "},
        {"instructions": "x" * 10_001},
        {"purpose": "x\x07"},
        {"model": "some-model"},
    ],
)
def test_a_version_that_breaks_todays_rules_is_refused(v, db_session, caplog, broken) -> None:
    caplog.set_level(logging.DEBUG)
    values = {"name": "Secret old name", "instructions": "Secret old text"} | broken
    fill(db_session, v.agent_id, 4, **values)
    fill(db_session, v.agent_id, 5)
    before = rows(db_session)
    response = roll_back(v.owner, v.one, 4, 5)
    assert (response.status_code, code(response)) == (409, "version_invalid")
    assert "Secret" not in response.text and "Secret" not in caplog.text
    assert rows(db_session) == before


def test_rollbacks_count_toward_the_write_limit(v, configure) -> None:
    one, url = v.one, version_url(v.owner, v.one, 1)
    configure(agent_write_limit=3)  # the fixture used two: create and one edit
    assert v.owner.post(f"{url}/rollback", json={"version": 3}).status_code == 200
    assert v.owner.post(f"{url}/rollback", json={"version": 4}).status_code == 429
    assert v.owner.post(f"{url}/rollback", json={}).status_code == 429
    assert v.owner.get(f"{one}/versions").status_code == v.owner.get(url).status_code == 200
    assert v.member.post(f"{url}/rollback", json={"version": 4}).status_code == 200


def test_outsiders_and_wrong_ids_are_not_counted(v, configure) -> None:
    url = version_url(v.owner, v.one, 1)
    configure(agent_write_limit=1)
    for _ in range(3):
        assert v.outsider.post(f"{url}/rollback", json={"version": 3}).status_code == 404
        wrong = f"{v.one}/versions/{uuid.uuid4()}/rollback"
        assert v.member.post(wrong, json={"version": 3}).status_code in (404,)
    # The member made one edit in the fixture, which is the whole limit.
    assert v.member.post(f"{url}/rollback", json={"version": 3}).status_code == 429


def test_another_agents_version_is_not_found(v, db_session) -> None:
    other = f"{v.url}/{create(v.owner, v.url, name='Other')['id']}"
    edit(v.owner, other, 1, name="Other 2")
    foreign = version_url(v.owner, other, 1).rsplit("/", 1)[1]
    before = rows(db_session)
    missing = v.owner.get(f"{v.one}/versions/{uuid.uuid4()}")
    for response in (
        v.owner.get(f"{v.one}/versions/{foreign}"),
        v.owner.post(f"{v.one}/versions/{foreign}/rollback", json={"version": 3}),
        missing,
    ):
        assert (response.status_code, code(response)) == (404, "not_found")
        assert "Other" not in response.text
    assert rows(db_session) == before


def test_the_service_checks_the_agent_too(v, db_session) -> None:
    """A second layer: the route's check alone must not be what stops a foreign version."""
    other = f"{v.url}/{create(v.owner, v.url, name='Other')['id']}"
    foreign = uuid.UUID(version_url(v.owner, other, 1).rsplit("/", 1)[1])
    agent = db_session.get(Agent, v.agent_id)
    context = WorkspaceContext(
        db_session.get(Workspace, agent.workspace_id), uuid.UUID(v.owner_id), "owner"
    )
    for call in (
        lambda: service.read_version(db_session, context, v.agent_id, foreign),
        lambda: service.roll_back(db_session, context, v.agent_id, foreign, 3),
    ):
        with pytest.raises(service.NotFoundError):
            call()
    assert count(db_session, AgentVersion, AgentVersion.agent_id == v.agent_id) == 3


def test_the_service_checks_the_workspace_too(v, db_session) -> None:
    """A second layer: the owner of another workspace, with the right agent and version ids."""
    version = uuid.UUID(version_url(v.owner, v.one, 1).rsplit("/", 1)[1])
    elsewhere = v.outsider.get("/api/workspaces").json()[0]["id"]
    outsider = uuid.UUID(v.outsider.get("/api/auth/me").json()["id"])
    context = WorkspaceContext(db_session.get(Workspace, uuid.UUID(elsewhere)), outsider, "owner")
    for call in (
        lambda: service.list_versions(db_session, context, v.agent_id, None),
        lambda: service.read_version(db_session, context, v.agent_id, version),
        lambda: service.roll_back(db_session, context, v.agent_id, version, 3),
    ):
        with pytest.raises(service.NotFoundError):
            call()
    assert count(db_session, AgentVersion, AgentVersion.agent_id == v.agent_id) == 3


def test_deleting_an_agent_with_rollbacks_removes_everything(v, db_session) -> None:
    roll_back(v.owner, v.one, 1, 3)
    assert v.owner.delete(v.one).status_code == 204
    assert db_session.scalar(select(AgentVersion.id)) is None
    assert v.owner.get(f"{v.one}/versions").status_code == 404
