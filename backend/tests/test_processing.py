"""Document processing: the job queue, the worker step, extraction, chunks, failures."""

# The imported fixtures are used as arguments.
# ruff: noqa: F401, F811

import io
import logging
import os
import subprocess
import sys
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import select, update

from app import worker
from app.core import clock
from app.models import Job, KnowledgeChunk, KnowledgeSource
from app.modules.jobs import service as jobs
from app.modules.knowledge import chunking, extract, processing, storage
from tests.test_agents_api import code, count, create, s
from tests.test_conversations import c
from tests.test_knowledge import DOCX_TYPE, TEXT, docx, upload

pytestmark = pytest.mark.db


def pdf(*pages: str) -> bytes:
    """A real PDF with a text layer: one page per string, an empty string for a page without."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        None,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content = len(objects)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>"
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out


def encrypted_pdf() -> bytes:
    from pypdf import PdfReader

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf("Secret roses"))))
    writer.encrypt(user_password="petal", owner_password="pine")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def run(db_session) -> bool:
    return worker.run_once(db_session)


def source(db_session) -> KnowledgeSource:
    db_session.expire_all()
    return db_session.scalars(select(KnowledgeSource)).one()


def chunks(db_session) -> list[KnowledgeChunk]:
    return list(db_session.scalars(select(KnowledgeChunk).order_by(KnowledgeChunk.sequence)))


def the_job(db_session) -> Job:
    db_session.expire_all()
    return db_session.scalars(select(Job)).one()


@pytest.mark.parametrize(
    ("body", "name", "content_type", "expected", "page"),
    [
        (TEXT, "notes.txt", "text/plain", "Petal & Pine opens at nine.", None),
        (b"# Roses\n\nRed ones.\n", "roses.md", "text/markdown", "# Roses", None),
        (docx(), "hours.docx", DOCX_TYPE, "Petal & Pine", None),
        (
            pdf("Tulips cost three euros"),
            "price.pdf",
            "application/pdf",
            "Tulips cost three euros",
            1,
        ),
    ],
)
def test_each_type_becomes_chunks(c, db_session, body, name, content_type, expected, page) -> None:
    assert upload(c, body, name, content_type).status_code == 201
    assert source(db_session).status == "pending"  # the request did no processing
    assert count(db_session, KnowledgeChunk) == 0
    assert run(db_session) is True
    found = source(db_session)
    assert (found.status, found.error_code) == ("ready", None)
    stored = chunks(db_session)
    assert expected in stored[0].content and stored[0].page == page
    assert all(
        (chunk.workspace_id, chunk.agent_id) == (found.workspace_id, found.agent_id)
        for chunk in stored
    )
    assert the_job(db_session).status == "succeeded"
    assert run(db_session) is False  # nothing left
    listed = c.member.get(f"{c.agent_url}/sources").json()["items"][0]
    assert (listed["status"], listed["error_code"]) == ("ready", None)


def test_pages_are_kept_and_empty_pages_skipped(c, db_session) -> None:
    upload(c, pdf("First page roses", "", "Third page tulips"), "p.pdf", "application/pdf")
    run(db_session)
    assert [(chunk.page, chunk.content) for chunk in chunks(db_session)] == [
        (1, "First page roses"),
        (3, "Third page tulips"),
    ]


@pytest.mark.parametrize(
    ("body", "name", "content_type", "error"),
    [
        (pdf("", ""), "scan.pdf", "application/pdf", "text_empty"),  # no text layer, no OCR
        (encrypted_pdf(), "locked.pdf", "application/pdf", "text_unreadable"),
        (b"%PDF-1.4\ngarbage that is no pdf at all\n%%EOF\n", "bad.pdf", "application/pdf",
         "text_unreadable"),
        (docx(types=b"<Types/>").replace(b"word/document.xml", b"word/documenx.xml"), "x.docx",
         DOCX_TYPE, "text_unreadable"),
    ],
)  # fmt: skip
def test_unreadable_documents_fail_honestly_without_retry(
    c, db_session, caplog, body, name, content_type, error
) -> None:
    response = upload(c, body, name, content_type)
    if response.status_code != 201:  # refused at upload already: just as honest
        assert response.status_code in (415, 422)
        return
    with caplog.at_level(logging.DEBUG):
        run(db_session)
    found = source(db_session)
    assert (found.status, found.error_code) == ("failed", error)
    job = the_job(db_session)
    assert (job.status, job.last_error, job.attempts) == ("failed", error, 1)
    assert count(db_session, KnowledgeChunk) == 0
    assert "roses" not in caplog.text.lower()
    out = c.member.get(f"{c.agent_url}/sources/{found.id}").json()
    assert out["error_code"] == error and out["error_message"]


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
WORD = f"<w:document {W_NS}><w:body><w:p><w:r><w:t>&a;&a;</w:t></w:r></w:p></w:body></w:document>"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_a_docx_with_a_dtd_is_unreadable(tmp_path, encoding) -> None:
    """Entities could multiply a small file into gigabytes. Refused in any encoding."""
    xml = f'<?xml version="1.0" encoding="{encoding}"?><!DOCTYPE x [<!ENTITY a "roses">]>{WORD}'
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", xml.encode(encoding))
    path = tmp_path / "x"
    path.write_bytes(body.getvalue())
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract(path, "docx")
    assert caught.value.code == "text_unreadable"
    # The same document without the DTD is read: the refusal is the DTD's.
    plain = io.BytesIO()
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", WORD.replace("&a;&a;", "roses").encode(encoding))
    path.write_bytes(plain.getvalue())
    assert extract.extract(path, "docx") == [(None, "roses")]


def test_the_real_unpacked_size_is_counted(tmp_path, monkeypatch) -> None:
    """The archive's directory claims a tiny size; the bytes really unpacked are what count."""
    body = io.BytesIO()
    text = "r" * 5000
    big = (
        f"<w:document {W_NS}><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(body, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", big)
    data = bytearray(body.getvalue())
    central = data.find(b"PK\x01\x02", data.find(b"word/document.xml") + 1)
    while central != -1:  # every central directory entry: claim 10 bytes unpacked
        data[central + 24 : central + 28] = (10).to_bytes(4, "little")
        central = data.find(b"PK\x01\x02", central + 1)
    path = tmp_path / "x"
    path.write_bytes(bytes(data))
    with zipfile.ZipFile(path) as archive:
        assert archive.getinfo("word/document.xml").file_size == 10  # the lie
    monkeypatch.setattr(extract, "MAX_DOCX_XML_BYTES", 1000)
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract(path, "docx")
    assert caught.value.code in ("text_too_long", "text_unreadable")


def test_page_and_length_limits(tmp_path, monkeypatch) -> None:
    path = tmp_path / "x"
    path.write_bytes(pdf("one", "two", "three"))
    monkeypatch.setattr(extract, "MAX_PAGES", 2)
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract(path, "pdf")
    assert caught.value.code == "pages_too_many"
    monkeypatch.setattr(extract, "MAX_PAGES", 500)
    monkeypatch.setattr(extract, "MAX_CHARACTERS", 5)
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract(path, "pdf")
    assert caught.value.code == "text_too_long"
    path.write_text("x" * 6, encoding="utf-8")
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract(path, "txt")
    assert caught.value.code == "text_too_long"


def test_a_stuck_extraction_is_stopped_and_retried_later(c, db_session, monkeypatch) -> None:
    monkeypatch.setattr(processing, "TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(
        processing,
        "command",
        lambda kind, path: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    upload(c, TEXT)
    started = clock.now()
    run(db_session)
    job = the_job(db_session)
    assert (job.status, job.last_error, job.attempts) == ("queued", "processing_timeout", 1)
    assert job.run_after >= started + timedelta(seconds=30)
    assert (source(db_session).status, source(db_session).error_code) == ("pending", None)
    assert run(db_session) is False  # not due yet


def test_retries_back_off_and_end_after_three_attempts(c, db_session, monkeypatch, advance) -> None:
    monkeypatch.setattr(processing, "command", lambda kind, path: [sys.executable, "-c", "pass"])
    upload(c, TEXT)
    waits = []
    for attempt in range(3):
        advance(minutes=30 * attempt)  # from the test's start
        before = clock.now()
        assert run(db_session) is True
        job = the_job(db_session)
        waits.append(job.run_after - before)
    advance(minutes=200)
    assert (job.status, job.last_error, job.attempts) == ("failed", "processing_failed", 3)
    assert (source(db_session).status, source(db_session).error_code) == (
        "failed",
        "processing_failed",
    )
    assert waits[0] >= timedelta(seconds=30) and waits[1] >= timedelta(minutes=2)
    assert run(db_session) is False


def test_a_worker_that_died_is_taken_over_once_its_lease_ends(c, db_session, advance) -> None:
    upload(c, TEXT)
    job = jobs.claim(db_session, processing.LEASE)  # a worker claims it and dies
    assert job is not None and run(db_session) is False
    advance(seconds=processing.LEASE.total_seconds() + 1)
    assert run(db_session) is True
    assert source(db_session).status == "ready" and the_job(db_session).attempts == 2


def test_a_job_whose_attempts_all_died_is_given_up(c, db_session, advance) -> None:
    upload(c, TEXT)
    lease = processing.LEASE.total_seconds() + 1
    for attempt in range(1, 4):
        assert jobs.claim(db_session, processing.LEASE) is not None
        advance(seconds=lease * attempt)  # from the test's start
    assert run(db_session) is False
    job = the_job(db_session)
    assert (job.status, job.last_error) == ("failed", "attempts_exhausted")
    found = source(db_session)  # not left "in progress" forever
    assert (found.status, found.error_code) == ("failed", "processing_failed")


def test_enqueueing_twice_makes_one_job_and_running_twice_one_set_of_chunks(c, db_session) -> None:
    upload(c, TEXT)
    found = source(db_session)
    jobs.enqueue(db_session, "process_source", found.id)
    db_session.commit()
    assert count(db_session, Job) == 1
    run(db_session)
    first = [chunk.content for chunk in chunks(db_session)]
    jobs.enqueue(db_session, "process_source", found.id)  # the earlier one is finished
    db_session.commit()
    run(db_session)
    assert [chunk.content for chunk in chunks(db_session)] == first
    assert count(db_session, Job) == 2


def test_a_source_deleted_during_processing_stays_deleted(c, db_session, monkeypatch) -> None:
    created = upload(c, TEXT).json()
    real = processing._extract

    def delete_meanwhile(path, kind):
        result = real(path, kind)
        assert c.member.delete(f"{c.agent_url}/sources/{created['id']}").status_code == 204
        return result

    monkeypatch.setattr(processing, "_extract", delete_meanwhile)
    run(db_session)
    assert count(db_session, KnowledgeSource) == 0 and count(db_session, KnowledgeChunk) == 0
    assert the_job(db_session).status == "succeeded"


def test_a_source_deleted_before_its_turn_is_skipped(c, db_session) -> None:
    created = upload(c, TEXT).json()
    c.member.delete(f"{c.agent_url}/sources/{created['id']}")
    assert run(db_session) is True
    assert the_job(db_session).status == "succeeded" and count(db_session, KnowledgeChunk) == 0


def test_a_missing_file_fails_without_retry(c, db_session) -> None:
    upload(c, TEXT)
    storage.path_of(source(db_session).storage_name).unlink()
    run(db_session)
    assert (source(db_session).status, source(db_session).error_code) == ("failed", "file_missing")
    assert the_job(db_session).status == "failed"


def test_a_crash_in_the_handler_is_retried_and_logs_no_text(
    c, db_session, monkeypatch, caplog
) -> None:
    upload(c, TEXT)

    def crash(db, job):
        raise ValueError("Petal & Pine opens at nine.")

    monkeypatch.setitem(worker.HANDLERS, "process_source", crash)
    with caplog.at_level(logging.DEBUG):
        assert run(db_session) is True
    assert "Petal" not in caplog.text
    job = the_job(db_session)
    assert (job.status, job.last_error) == ("queued", "processing_failed")


def test_a_child_crash_reveals_nothing(c, db_session, monkeypatch, caplog) -> None:
    script = "import sys; sys.stderr.write('Petal & Pine secret'); sys.exit(3)"
    monkeypatch.setattr(processing, "command", lambda kind, path: [sys.executable, "-c", script])
    upload(c, TEXT)
    with caplog.at_level(logging.DEBUG):
        run(db_session)
    assert "Petal" not in caplog.text
    assert the_job(db_session).last_error == "processing_failed"


@pytest.mark.parametrize(
    "output",
    ['{"error": "Petal secret"}', '{"pages": [[0, "x"]]}', '{"pages": [["1", "x"]]}', "[]", "x"],
)
def test_unexpected_child_output_is_a_failure(c, db_session, monkeypatch, output) -> None:
    script = f"import sys; sys.stdout.write({output!r})"
    monkeypatch.setattr(processing, "command", lambda kind, path: [sys.executable, "-c", script])
    upload(c, TEXT)
    run(db_session)
    assert the_job(db_session).last_error == "processing_failed"


def test_a_worker_whose_lease_ran_out_changes_nothing(c, db_session, advance) -> None:
    """Another worker took the job over; the slow one must not overwrite its bookkeeping."""
    upload(c, TEXT)
    slow = jobs.claim(db_session, processing.LEASE)
    advance(seconds=processing.LEASE.total_seconds() + 1)
    fast = jobs.claim(db_session, processing.LEASE)
    assert fast is not None and fast.attempts == 2
    slow.locked_until = slow.locked_until - processing.LEASE  # its own, older claim
    processing.record_failure(db_session, slow, "processing_timeout")
    job = the_job(db_session)
    assert (job.status, job.attempts, job.last_error) == ("running", 2, None)


def test_the_worker_process_knows_every_table(tmp_path) -> None:
    """It imports less than the API: foreign keys to other modules must still resolve."""
    script = (
        "import app.worker, sqlalchemy.orm as orm; orm.configure_mappers(); "
        "from app.core.database import Base; "
        "[fk.column for table in Base.metadata.tables.values() for fk in table.foreign_keys]"
    )
    done = subprocess.run(  # noqa: S603 - our own interpreter and arguments
        [sys.executable, "-c", script], cwd=processing.BACKEND_DIR, capture_output=True, check=False
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-300:]


def test_the_child_is_stopped_when_it_takes_too_much_memory(tmp_path) -> None:
    path = tmp_path / "x"
    path.write_bytes(TEXT)
    done = subprocess.run(  # noqa: S603 - our own interpreter and arguments
        processing.command("txt", path),
        cwd=processing.BACKEND_DIR,
        capture_output=True,
        timeout=60,
        check=False,
        env={**os.environ, "AGENTLY_EXTRACT_MEMORY_MB": "1"},
    )
    assert b"Petal" not in done.stdout and b"Petal" not in done.stderr
    if sys.platform == "win32":
        assert done.stdout == b'{"error": "text_too_long"}'


def test_a_failing_sweep_does_not_stop_the_worker(monkeypatch) -> None:
    calls = []

    def broken_sweep() -> None:
        calls.append("sweep")
        raise OSError("disk")

    def step(db=None) -> bool:
        calls.append("step")
        raise SystemExit  # ends the loop after one step

    monkeypatch.setattr(worker, "sweep", broken_sweep)
    monkeypatch.setattr(worker, "run_once", step)
    monkeypatch.setattr(worker.signal, "signal", lambda *args: None)
    with pytest.raises(SystemExit):
        worker.main()
    assert calls == ["sweep", "step"]


def test_the_child_prints_only_its_result(tmp_path, capsys) -> None:
    path = tmp_path / "x"
    path.write_bytes(TEXT)
    assert extract.main(["txt", str(path)]) == 0
    assert capsys.readouterr().out.startswith('{"pages": [[null, "Petal')
    assert extract.main(["exe", str(path)]) == 0
    assert capsys.readouterr().out == '{"error": "processing_failed"}'


def test_chunks_overlap_and_prefer_breaks() -> None:
    sentence = "Roses are red and tulips are yellow. "
    text = sentence * 100  # 3,700 characters
    pieces = chunking.chunk([(None, text)])
    assert len(pieces) >= 3
    assert [piece.sequence for piece in pieces] == list(range(len(pieces)))
    assert all(len(piece.content) <= chunking.CHUNK_CHARACTERS for piece in pieces)
    assert all(piece.content.endswith(".") for piece in pieces[:-1])
    for first, second in zip(pieces, pieces[1:], strict=False):
        assert second.content[:40] in first.content  # the overlap
    assert chunking.chunk([(1, "   ")]) == []
    assert [piece.content for piece in chunking.chunk([(2, "short")])] == ["short"]


def test_the_database_keeps_chunks_with_their_own_source(c, db_session) -> None:
    upload(c, TEXT)
    run(db_session)
    other = f"{c.url}/{create(c.owner, c.url)['id']}"
    for values in ({"agent_id": uuid.UUID(other.rsplit("/", 1)[1])}, {"page": 0}, {"content": ""}):
        with pytest.raises(Exception, match="knowledge_chunks"), db_session.begin_nested():
            db_session.execute(update(KnowledgeChunk).values(**values))


def test_jobs_hold_no_content_and_the_database_checks_them(c, db_session) -> None:
    columns = set(Job.__table__.columns.keys())
    assert columns == {
        "id", "kind", "subject_id", "status", "attempts", "max_attempts", "run_after",
        "locked_until", "last_error", "created_at", "updated_at",
    }  # fmt: skip
    upload(c, TEXT)
    for values in ({"status": "done"}, {"kind": "x"}, {"attempts": 9}, {"status": "running"}):
        with pytest.raises(Exception, match="ck_jobs"), db_session.begin_nested():
            db_session.execute(update(Job).values(**values))
