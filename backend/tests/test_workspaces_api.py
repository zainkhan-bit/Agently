"""Workspaces and membership rules over HTTP."""

import pytest
from sqlalchemy import func, select

from app.models import Membership, User, Workspace
from app.modules.workspaces import service
from tests.auth_helpers import register

pytestmark = pytest.mark.db


@pytest.fixture
def person(make_client):
    """Register someone. Returns (client, user id, personal workspace id)."""

    def make(name: str):
        client = make_client()
        user_id = register(client, email=f"{name}@example.com").json()["id"]
        return client, user_id, client.get("/api/workspaces").json()[0]["id"]

    return make


@pytest.fixture
def team(person, db_session):
    """Owner's workspace with one plain member."""
    owner, owner_id, workspace_id = person("owner")
    member, member_id, _ = person("member")
    db_session.add(Membership(user_id=member_id, workspace_id=workspace_id, role="member"))
    db_session.commit()

    class Team:
        pass

    team = Team()
    team.owner, team.owner_id, team.member, team.member_id = owner, owner_id, member, member_id
    team.url = f"/api/workspaces/{workspace_id}"
    team.owner_url = f"{team.url}/members/{owner_id}"
    team.member_url = f"{team.url}/members/{member_id}"
    return team


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def set_role(client, url, role):
    return client.patch(url, json={"role": role})


def error(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def test_registration_creates_one_owned_workspace(api) -> None:
    register(api)
    (workspace,) = api.get("/api/workspaces").json()
    assert set(workspace) == {"id", "name", "role", "created_at"}
    assert workspace["role"] == "owner"


@pytest.mark.parametrize("step", ["add_workspace", "create_session"])
def test_failed_registration_leaves_nothing_behind(auth_app, db_session, monkeypatch, step) -> None:
    from fastapi.testclient import TestClient

    from app.modules.identity import service as identity
    from tests.auth_helpers import ORIGIN

    target = identity.workspaces if step == "add_workspace" else identity.sessions
    monkeypatch.setattr(target, step, lambda *_: 1 / 0)
    client = TestClient(
        auth_app,
        base_url="https://testserver",
        headers={"Origin": ORIGIN},
        raise_server_exceptions=False,
    )
    assert register(client).status_code == 500
    assert [count(db_session, model) for model in (User, Workspace, Membership)] == [0, 0, 0]


def test_create_list_rename_and_delete(person, db_session) -> None:
    client, _, personal = person("a")
    created = client.post("/api/workspaces", json={"name": "  Team A  "})
    assert created.status_code == 201
    assert (created.json()["name"], created.json()["role"]) == ("Team A", "owner")
    url = f"/api/workspaces/{created.json()['id']}"
    assert client.get(url).json() == created.json()

    renamed = client.patch(url, json={"name": "Team B"})
    assert renamed.json() == {**created.json(), "name": "Team B"}
    assert client.get(url).json()["name"] == "Team B"

    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert [w["id"] for w in client.get("/api/workspaces").json()] == [personal]
    assert count(db_session, User) == 1


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "x" * 101,
        "a\x00b",
        "a\nb",
        "\x1b[31m",
        "\u200b",
        "\u200d\ufe0f",
        "a\u202eb",
        "a\u2028b",
    ],
)
def test_invalid_names_are_rejected(person, name) -> None:
    client, _, personal = person("a")
    assert client.post("/api/workspaces", json={"name": name}).status_code == 422
    assert client.patch(f"/api/workspaces/{personal}", json={"name": name}).status_code == 422


@pytest.mark.parametrize("name", ["x", "x" * 100, "Équipe 👩‍🚀"])
def test_valid_names_are_accepted(person, name) -> None:
    client, _, _ = person("a")
    assert client.post("/api/workspaces", json={"name": name}).json()["name"] == name


def test_role_and_owner_fields_in_the_body_are_ignored(person, db_session) -> None:
    client, user_id, _ = person("a")
    _, other_id, _ = person("b")
    body = {"name": "W", "role": "member", "user_id": other_id, "owner_id": other_id}
    workspace_id = client.post("/api/workspaces", json=body).json()["id"]
    members = client.get(f"/api/workspaces/{workspace_id}/members").json()
    assert members == [{"user_id": user_id, "email": "a@example.com", "role": "owner"}]


def test_members_see_the_member_list(team) -> None:
    expected = [
        {"user_id": team.member_id, "email": "member@example.com", "role": "member"},
        {"user_id": team.owner_id, "email": "owner@example.com", "role": "owner"},
    ]
    for client in (team.owner, team.member):
        assert client.get(f"{team.url}/members").json() == expected
    assert team.member.get(team.url).json()["role"] == "member"


def test_member_cannot_do_owner_actions(team) -> None:
    for response in (
        team.member.patch(team.url, json={"name": "Mine"}),
        team.member.delete(team.url),
        set_role(team.member, team.member_url, "owner"),
        set_role(team.member, team.owner_url, "member"),
        team.member.delete(team.owner_url),
        team.member.delete(team.member_url),
    ):
        assert error(response) == (403, "permission_denied")
    roles = {m["user_id"]: m["role"] for m in team.owner.get(f"{team.url}/members").json()}
    assert roles == {team.owner_id: "owner", team.member_id: "member"}
    assert team.owner.get(team.url).json()["name"] != "Mine"


def test_last_owner_cannot_leave_be_removed_or_demoted(team) -> None:
    for response in (
        team.owner.post(f"{team.url}/leave"),
        team.owner.delete(team.owner_url),
        set_role(team.owner, team.owner_url, "member"),
    ):
        assert error(response) == (409, "last_owner")
    assert team.owner.get(team.url).json()["role"] == "owner"


def test_ownership_can_be_handed_over(team) -> None:
    promoted = set_role(team.owner, team.member_url, "owner")
    assert promoted.json() == {
        "user_id": team.member_id,
        "email": "member@example.com",
        "role": "owner",
    }
    assert team.owner.post(f"{team.url}/leave").status_code == 204
    assert team.owner.get(team.url).status_code == 404
    assert error(team.member.post(f"{team.url}/leave")) == (409, "last_owner")
    assert team.member.delete(team.url).status_code == 204


def test_owner_can_demote_another_owner(team) -> None:
    set_role(team.owner, team.member_url, "owner")
    assert set_role(team.owner, team.member_url, "member").json()["role"] == "member"
    assert error(team.member.delete(team.url)) == (403, "permission_denied")


@pytest.mark.parametrize("role", ["owner", "member"])
def test_setting_the_current_role_changes_nothing(team, role) -> None:
    url = team.owner_url if role == "owner" else team.member_url
    assert set_role(team.owner, url, role).json()["role"] == role


def test_unknown_role_is_rejected(team) -> None:
    assert set_role(team.owner, team.member_url, "admin").status_code == 422


def test_removed_member_loses_access_at_once(team) -> None:
    assert team.owner.delete(team.member_url).status_code == 204
    assert team.member.get(team.url).status_code == 404
    assert team.member.get(f"{team.url}/members").status_code == 404
    assert error(team.owner.delete(team.member_url)) == (404, "not_found")


def test_member_can_leave(team) -> None:
    assert team.member.post(f"{team.url}/leave").status_code == 204
    assert team.member.get(team.url).status_code == 404
    assert len(team.owner.get(f"{team.url}/members").json()) == 1


def test_people_outside_the_workspace_are_not_valid_targets(team, person) -> None:
    _, outsider_id, _ = person("outsider")
    url = f"{team.url}/members/{outsider_id}"
    assert error(set_role(team.owner, url, "owner")) == (404, "not_found")
    assert error(team.owner.delete(url)) == (404, "not_found")


def test_deleting_a_workspace_keeps_its_people(team, db_session) -> None:
    assert team.owner.delete(team.url).status_code == 204
    assert count(db_session, User) == 2
    assert count(db_session, Membership) == 1  # the member's personal workspace


def test_limit_counts_the_personal_workspace(person) -> None:
    client, _, _ = person("a")
    for n in range(19):
        assert client.post("/api/workspaces", json={"name": f"W{n}"}).status_code == 201
    response = client.post("/api/workspaces", json={"name": "One too many"})
    assert error(response) == (409, "workspace_limit")
    assert len(client.get("/api/workspaces").json()) == 20


def test_limit_does_not_count_workspaces_owned_by_others(team, monkeypatch) -> None:
    monkeypatch.setattr(service, "MAX_OWNED_WORKSPACES", 2)
    assert len(team.member.get("/api/workspaces").json()) == 2
    assert team.member.post("/api/workspaces", json={"name": "W"}).status_code == 201


def test_promotion_respects_the_limit(team, monkeypatch) -> None:
    monkeypatch.setattr(service, "MAX_OWNED_WORKSPACES", 1)
    assert error(set_role(team.owner, team.member_url, "owner")) == (409, "workspace_limit")


def test_deleting_the_only_workspace_allows_a_new_one(person) -> None:
    client, _, personal = person("a")
    client.delete(f"/api/workspaces/{personal}")
    assert client.get("/api/workspaces").json() == []
    assert client.post("/api/workspaces", json={"name": "New"}).status_code == 201


@pytest.mark.parametrize("field", ["id", "members"])
def test_malformed_ids_are_validation_errors(team, field) -> None:
    url = "/api/workspaces/not-a-uuid" if field == "id" else f"{team.url}/members/not-a-uuid"
    assert team.owner.delete(url).status_code == 422
