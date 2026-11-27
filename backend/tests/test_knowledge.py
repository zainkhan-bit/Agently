"""Knowledge sources: upload checks, private storage, limits, deletion."""

# The imported fixtures are used as arguments.
# ruff: noqa: F401, F811

import io
import logging
import os
import time
import uuid
import zipfile
from urllib.parse import quote

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.models import KnowledgeSource
from app.modules.knowledge import filetypes, storage
from tests.test_agents_api import code, count, create, s
from tests.test_conversations import c

pytestmark = pytest.mark.db

DOCX_TYPE = filetypes.DOCX_TYPE
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
TEXT = b"Petal & Pine opens at nine.\nRoses are on the left.\n"


def docx(extra: dict[str, bytes] | None = None, *, types: bytes = b"<Types/>") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("word/document.xml", "<w:document>Petal &amp; Pine</w:document>")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def upload(c, body: bytes, name="notes.txt", content_type="text/plain", client=None, url=None):
    headers = {"X-File-Name": quote(name)}
    if content_type is not None:
        headers["Content-Type"] = content_type
    return (client or c.member).post(url or f"{c.agent_url}/sources", content=body, headers=headers)


def files() -> list[str]:
    """Stored files, then files still in the incoming folder."""
    folder = storage.root()
    return sorted(
        path.name for path in folder.iterdir() if storage.NAME.fullmatch(path.name)
    ) + sorted(path.name for path in (folder / storage.INCOMING).iterdir())


@pytest.mark.parametrize(
    ("body", "name", "content_type", "kind"),
    [
        (PDF, "price list.pdf", "application/pdf", "pdf"),
        (docx(), "Opening hours.docx", DOCX_TYPE, "docx"),
        (TEXT, "notes.txt", "text/plain; charset=utf-8", "txt"),
        (b"\xef\xbb\xbf# Roses\n\nRed.\n", "roses.md", "text/markdown", "md"),
        (b"# Roses\n", "roses.markdown", "", "md"),
        (TEXT, "notes.TXT", "application/octet-stream", "txt"),
    ],
)
def test_supported_files_are_kept_privately(c, db_session, body, name, content_type, kind) -> None:
    response = upload(c, body, name, content_type)
    assert response.status_code == 201, response.text
    out = response.json()
    assert (out["name"], out["kind"], out["size_bytes"], out["status"]) == (
        name,
        kind,
        len(body),
        "pending",
    )
    assert set(out) == {
        "id", "agent_id", "name", "kind", "size_bytes", "status", "error_code",
        "created_at", "updated_at",
    }  # fmt: skip
    record = db_session.scalars(select(KnowledgeSource)).one()
    assert storage.NAME.fullmatch(record.storage_name)
    assert name not in record.storage_name
    assert storage.path_of(record.storage_name).read_bytes() == body
    assert files() == [record.storage_name]  # nothing left in incoming
    assert record.uploaded_by == uuid.UUID(c.member_id)


@pytest.mark.parametrize(
    "place",
    [
        storage.REPOSITORY,
        storage.REPOSITORY / "frontend" / "public" / "files",
        storage.BACKEND_DIR,
        storage.BACKEND_DIR / "knowledge",  # not ignored by git: a public repository
        storage.BACKEND_DIR / "app" / "static",
        storage.BACKEND_DIR / "var",
        "knowledge",  # relative to backend/
    ],
)
def test_the_storage_folder_is_outside_the_repository_or_in_var(configure, place) -> None:
    configure(knowledge_storage_dir=place)
    with pytest.raises(RuntimeError, match="KNOWLEDGE_STORAGE_DIR"):
        storage.root()


def test_the_default_storage_folder_is_ignored_by_git(configure) -> None:
    configure(knowledge_storage_dir="")
    assert storage.root() == storage.BACKEND_DIR / "var" / "knowledge"
    ignored = (storage.REPOSITORY / ".gitignore").read_text().splitlines()
    assert "backend/var/" in ignored


@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b.txt", "a\\b.txt", "x\x00.txt"])
def test_names_are_never_paths(c, db_session, name) -> None:
    assert storage.NAME.fullmatch(storage.new_name())
    with pytest.raises(ValueError, match="not a storage name"):
        storage.path_of("../" + "a" * 29)
    response = upload(c, TEXT, name)
    assert (response.status_code, code(response)) == (422, "file_name_invalid")
    assert count(db_session, KnowledgeSource) == 0 and files() == []


REFUSED = [
    # (body, name, content type, status, code)
    (TEXT, "notes.exe", "text/plain", 415, "file_type_unsupported"),
    (TEXT, "notes", "text/plain", 415, "file_type_unsupported"),
    (b"<svg onload=alert(1)/>", "logo.svg", "image/svg+xml", 415, "file_unsafe"),
    (b"<html><script>x</script></html>", "page.html", "text/html", 415, "file_unsafe"),
    (b"  <!DOCTYPE html><p>hi", "notes.txt", "text/plain", 415, "file_unsafe"),
    (b"\xef\xbb\xbf<svg xmlns='x'/>", "notes.md", "text/markdown", 415, "file_unsafe"),
    (b"<?xml version='1.0'?><svg/>", "notes.txt", "text/plain", 415, "file_unsafe"),
    (TEXT, "notes.txt", "text/html", 415, "file_unsafe"),
    (TEXT, "notes.txt", "image/png", 415, "file_type_mismatch"),
    (PDF, "notes.txt", "text/plain", 415, "file_type_mismatch"),
    (TEXT, "price.pdf", "application/pdf", 415, "file_type_mismatch"),
    (docx(), "price.pdf", "application/pdf", 415, "file_type_mismatch"),
    (PDF, "hours.docx", DOCX_TYPE, 415, "file_type_mismatch"),
    (PDF.replace(b"%%EOF", b""), "price.pdf", "application/pdf", 422, "file_malformed"),
    (PDF.replace(b"endobj", b"/OpenAction << /S /JavaScript >> endobj"), "price.pdf",
     "application/pdf", 415, "file_unsafe"),
    (PDF.replace(b"endobj", b"/Launch endobj"), "price.pdf", "application/pdf", 415,
     "file_unsafe"),
    (PDF.replace(b"endobj", b"/JS\n(app.alert(1)) endobj"), "price.pdf", "application/pdf", 415,
     "file_unsafe"),
    (docx({"word/vbaProject.bin": b"macro"}), "hours.docx", DOCX_TYPE, 415, "file_unsafe"),
    (docx(types=b"<Types application/vnd.ms-word.document.macroEnabled.main+xml/>"),
     "hours.docx", DOCX_TYPE, 415, "file_unsafe"),
    (docx({"bomb.xml": b"0" * 20_000_000}), "hours.docx", DOCX_TYPE, 415, "file_unsafe"),
    (b"PK\x03\x04 not really a zip", "hours.docx", DOCX_TYPE, 422, "file_malformed"),
    (b"\xff\xfe\x00b\x00a\x00d", "notes.txt", "text/plain", 422, "file_malformed"),
    (b"binary\x00text", "notes.txt", "text/plain", 422, "file_malformed"),
    (b"bell\x07", "notes.md", "text/markdown", 422, "file_malformed"),
    (b"   \n\t ", "notes.txt", "text/plain", 422, "file_empty"),
]  # fmt: skip


@pytest.mark.parametrize(("body", "name", "content_type", "status", "error"), REFUSED)
def test_unsupported_malformed_and_suspicious_files_are_refused(
    c, db_session, caplog, body, name, content_type, status, error
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = upload(c, body, name, content_type)
    assert (response.status_code, code(response)) == (status, error)
    assert count(db_session, KnowledgeSource) == 0 and files() == []
    logged = caplog.text
    assert name not in logged and "Petal" not in logged and "script" not in logged


def test_an_encrypted_entry_is_refused(c, db_session) -> None:
    body = bytearray(docx())
    # The general-purpose flag of the first local header and of its central directory entry.
    body[6] |= 0x1
    central = body.rfind(b"PK\x01\x02")
    while central != -1:
        body[central + 8] |= 0x1
        central = body.rfind(b"PK\x01\x02", 0, central)
    response = upload(c, bytes(body), "hours.docx", DOCX_TYPE)
    assert (response.status_code, code(response)) == (415, "file_unsafe")


def test_a_corrupt_entry_is_malformed_not_an_error(c, db_session) -> None:
    body = bytearray(docx(types=b"<Types>" + b"x" * 500 + b"</Types>"))
    start = body.index(b"[Content_Types].xml") + len("[Content_Types].xml")
    body[start : start + 20] = b"\xff" * 20  # the deflated bytes of that entry
    response = upload(c, bytes(body), "hours.docx", DOCX_TYPE)
    assert (response.status_code, code(response)) == (422, "file_malformed")


def test_the_claimed_unpacked_size_is_limited(c, db_session, monkeypatch) -> None:
    monkeypatch.setattr(filetypes, "ZIP_MAX_UNPACKED", 10)
    response = upload(c, docx(), "hours.docx", DOCX_TYPE)
    assert (response.status_code, code(response)) == (415, "file_unsafe")


def test_too_many_entries_are_refused(c, db_session) -> None:
    body = docx({f"word/media/{n}.xml": b"x" for n in range(filetypes.ZIP_MAX_ENTRIES)})
    response = upload(c, body, "hours.docx", DOCX_TYPE)
    assert (response.status_code, code(response)) == (415, "file_unsafe")


def test_size_is_limited_before_and_while_reading(c, db_session, configure) -> None:
    configure(knowledge_max_file_bytes=100)
    too_big = b"a" * 101
    response = upload(c, too_big)
    assert (response.status_code, code(response)) == (413, "file_too_large")

    def chunks():
        yield b"a" * 60
        yield b"a" * 60

    # A body without a length is refused before it is read.
    response = c.member.post(
        f"{c.agent_url}/sources", headers={"X-File-Name": "a.txt"}, content=chunks()
    )
    assert (response.status_code, code(response)) == (411, "length_required")
    assert upload(c, b"a" * 100).status_code == 201
    assert count(db_session, KnowledgeSource) == 1 and len(files()) == 1


def test_a_body_longer_than_its_length_is_cut_off(c, db_session, configure) -> None:
    """The body is counted, not the header believed."""
    configure(knowledge_max_file_bytes=100)
    from app.modules.knowledge import router

    class Lying:
        headers = {"content-length": "10"}

        async def stream(self):
            yield b"a" * 60
            yield b"a" * 60

    import anyio

    with pytest.raises(filetypes.FileTooLargeError):
        anyio.run(router._receive, Lying(), 100)
    Lying.headers = {"content-length": "120"}
    with pytest.raises(filetypes.FileTooLargeError):
        anyio.run(router._receive, Lying(), 100)
    assert files() == []


def test_an_empty_body_is_refused(c, db_session) -> None:
    response = upload(c, b"")
    assert (response.status_code, code(response)) == (422, "file_empty")


def test_the_workspace_cap_counts_every_agent(c, db_session, configure) -> None:
    configure(knowledge_storage_limit_per_workspace_bytes=len(TEXT) * 2)
    other = f"{c.url}/{create(c.owner, c.url)['id']}/sources"
    assert upload(c, TEXT).status_code == 201
    assert upload(c, TEXT + b"2", url=other).status_code == 409
    assert upload(c, TEXT[:-1], url=other).status_code == 201
    response = upload(c, b"xy")
    assert (response.status_code, code(response)) == (409, "storage_limit")
    assert len(files()) == 2


def test_sources_per_agent_and_duplicates_are_limited(c, db_session, configure) -> None:
    configure(knowledge_sources_per_agent=2)
    assert upload(c, TEXT).status_code == 201
    response = upload(c, TEXT, "again.txt")
    assert (response.status_code, code(response)) == (409, "source_duplicate")
    assert upload(c, TEXT + b"2").status_code == 201
    response = upload(c, TEXT + b"3")
    assert (response.status_code, code(response)) == (409, "source_limit")
    assert len(files()) == 2


def test_uploads_are_rate_limited_per_person_and_workspace(c, db_session, configure) -> None:
    configure(knowledge_upload_limit_per_user=2, knowledge_upload_limit_per_workspace=3)
    assert upload(c, TEXT).status_code == 201
    assert upload(c, b"refused", "x.exe").status_code == 415  # refused uploads count
    assert code(upload(c, TEXT + b"2")) == "rate_limited"
    assert upload(c, TEXT + b"3", client=c.owner).status_code == 201
    assert code(upload(c, TEXT + b"4", client=c.owner)) == "rate_limited"
    # Outsiders count nothing.
    assert upload(c, TEXT, client=c.outsider).status_code == 404


def test_archived_agents_take_no_files_but_paused_ones_do(c, db_session) -> None:
    c.owner.post(f"{c.agent_url}/pause")
    assert upload(c, TEXT).status_code == 201
    c.owner.post(f"{c.agent_url}/archive")
    response = upload(c, TEXT + b"2")
    assert (response.status_code, code(response)) == (409, "agent_archived")


def test_members_list_read_and_delete_sources(c, db_session, advance) -> None:
    first = upload(c, TEXT).json()
    advance(minutes=1)
    second = upload(c, PDF, "b.pdf", "application/pdf", client=c.owner).json()
    listed = c.member.get(f"{c.agent_url}/sources").json()
    assert [item["id"] for item in listed["items"]] == [second["id"], first["id"]]
    assert listed["total"] == 2
    page = c.member.get(f"{c.agent_url}/sources", params={"limit": 1, "offset": 1}).json()
    assert [item["id"] for item in page["items"]] == [first["id"]]
    one = c.owner.get(f"{c.agent_url}/sources/{first['id']}")
    assert one.status_code == 200 and one.json() == first
    assert one.headers["Cache-Control"] == "private, no-store"
    assert c.owner.delete(f"{c.agent_url}/sources/{first['id']}").status_code == 204
    assert c.member.get(f"{c.agent_url}/sources/{first['id']}").status_code == 404
    assert c.member.delete(f"{c.agent_url}/sources/{first['id']}").status_code == 404
    record = db_session.scalars(select(KnowledgeSource)).one()
    assert files() == [record.storage_name]


def test_there_is_no_way_to_download_a_file(c) -> None:
    source = upload(c, TEXT).json()
    for path in ("/content", "/file", "/download", ""):
        response = c.member.get(f"{c.agent_url}/sources/{source['id']}{path}")
        assert "Petal" not in response.text


def test_deleting_the_agent_or_workspace_removes_the_files(c, db_session) -> None:
    upload(c, TEXT)
    other = f"{c.url}/{create(c.owner, c.url)['id']}"
    upload(c, PDF, "b.pdf", "application/pdf", url=f"{other}/sources")
    assert len(files()) == 2
    assert c.owner.delete(c.agent_url).status_code == 204
    assert len(files()) == 1 and count(db_session, KnowledgeSource) == 1
    assert c.owner.delete(f"/api/workspaces/{c.workspace}").status_code == 204
    assert files() == [] and count(db_session, KnowledgeSource) == 0


def test_a_file_whose_record_failed_is_removed(c, db_session, monkeypatch) -> None:
    """The file was placed under its final name; then the commit of its record fails."""
    placed, real_place, real_commit = [], storage.place, db_session.commit

    def place(*args):
        placed.append(real_place(*args))
        return placed[-1]

    def commit():
        if placed:
            raise RuntimeError("database down")
        real_commit()

    monkeypatch.setattr(storage, "place", place)
    monkeypatch.setattr(db_session, "commit", commit)
    with pytest.raises(RuntimeError):
        upload(c, TEXT)
    assert len(placed) == 1 and not placed[0].exists()
    assert files() == []


def test_no_connection_is_held_while_the_body_arrives(c, db_session, monkeypatch) -> None:
    """A slow upload must not keep a pooled connection in a transaction."""
    from app.modules.knowledge import router

    seen, real = [], router._receive

    async def receive(request, maximum):
        seen.append(db_session.in_transaction())
        return await real(request, maximum)

    monkeypatch.setattr(router, "_receive", receive)
    assert upload(c, TEXT).status_code == 201
    assert seen == [False]


def test_a_large_file_passes_the_app_wide_body_limit(c, db_session) -> None:
    body = b"Roses and tulips.\n" * 12_000  # about 200 KB, over the 64 KB of other routes
    assert len(body) > 200_000
    assert upload(c, body).status_code == 201


def test_names_come_percent_encoded_in_a_header(c, db_session, caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        response = upload(c, TEXT, "Prix des fleurs été.txt")
    assert response.json()["name"] == "Prix des fleurs été.txt"
    assert "fleurs" not in caplog.text
    bad = c.member.post(f"{c.agent_url}/sources", content=TEXT, headers={"X-File-Name": "%ff.txt"})
    assert (bad.status_code, code(bad)) == (422, "file_name_invalid")
    missing = c.member.post(f"{c.agent_url}/sources", content=TEXT)
    assert missing.status_code == 422


def test_the_sweep_removes_only_old_files_without_a_record(c, db_session) -> None:
    kept = upload(c, TEXT).json()
    record = db_session.scalars(select(KnowledgeSource)).one()
    orphan, fresh = storage.new_name(), storage.new_name()
    incoming_left = storage.incoming_path()
    for path in (storage.path_of(orphan), storage.path_of(fresh)):
        path.write_bytes(b"x")
    old = time.time() - storage.ORPHAN_AGE_SECONDS - 10
    for path in (storage.path_of(orphan), storage.path_of(record.storage_name), incoming_left):
        os.utime(path, (old, old))
    (storage.root() / "README").write_text("not ours")
    assert storage.sweep(db_session) == 2
    assert files() == sorted([record.storage_name, fresh])
    assert (storage.root() / "README").exists()
    assert c.member.get(f"{c.agent_url}/sources/{kept['id']}").status_code == 200


def test_the_database_refuses_false_records(c, db_session) -> None:
    upload(c, TEXT)
    for values in (
        {"storage_name": "../../etc/passwd"},
        {"kind": "svg"},
        {"status": "done"},
        {"size_bytes": 0},
        {"sha256": "x"},
    ):
        with pytest.raises(Exception, match="ck_knowledge_sources"), db_session.begin_nested():
            db_session.execute(update(KnowledgeSource).values(**values))


def test_only_the_upload_route_takes_large_bodies(c) -> None:
    from app.modules.knowledge.router import UPLOAD_BODY_CEILING

    big = {"name": "x" * 70_000, "instructions": "x"}
    assert c.owner.post(c.url, json=big).status_code == 413  # the app-wide limit stays
    field = __import__("app.core.config", fromlist=["Settings"]).Settings.model_fields
    ceiling = [m.le for m in field["knowledge_max_file_bytes"].metadata if hasattr(m, "le")]
    assert ceiling == [UPLOAD_BODY_CEILING]


def test_settings_have_safe_defaults() -> None:
    from app.core.config import Settings

    fields = Settings.model_fields
    assert fields["knowledge_max_file_bytes"].default == 10_000_000
    assert fields["knowledge_storage_limit_per_workspace_bytes"].default == 200_000_000
    assert fields["knowledge_upload_limit_per_user"].default == 30
    assert fields["knowledge_upload_limit_per_workspace"].default == 100
    assert get_settings() is not None
