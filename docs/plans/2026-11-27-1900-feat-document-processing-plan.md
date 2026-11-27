# Slice 4.2 — Asynchronous document processing

- **Date:** 2026-11-27 (owner away, working autonomously; doc review skipped by instruction)
- **Goal:** an uploaded source is turned into text chunks by a worker process, never inside a web
  request, with honest statuses and fixed failure reasons.
- **Sources:** `AGENT_BUILD_GUIDE.md` Slice 4.2, ADR-0004 (PostgreSQL job queue), `MASTER_PRD.md`
  KB-2, the owner's brief, the Slice 4.1 review (count the bytes really unpacked).
- **Stop conditions:** a document's text would reach a log, or processing would have to run in a
  request.

## Requirements

- R1. A `jobs` table (ADR-0004): kind, subject id, status (`queued`, `running`, `succeeded`,
  `failed`), attempts, maximum attempts, `run_after` (backoff), `locked_until` (lease), last error
  code, timestamps. One open job per kind and subject (partial unique index), so enqueueing twice
  creates one job.
- R2. The upload enqueues its job in the same transaction as the source record. Nothing else
  happens in the request.
- R3. A worker process (`python -m app.worker`) claims one job at a time with
  `FOR UPDATE SKIP LOCKED`, also an expired lease of a worker that died. It also runs the orphan
  file sweep now and then.
- R4. Extraction runs in a child process with a per-document timeout (60 s), so a stuck parser is
  killed. Limits: 500 PDF pages, 2,000,000 extracted characters, 20 MB of really unpacked DOCX XML
  (counted while reading, not taken from the archive's claims), no DTDs in DOCX XML.
- R5. Text: PDF with pypdf (page numbers kept), DOCX paragraphs from `word/document.xml`, TXT and
  Markdown as stored. No OCR: a PDF without a text layer fails as `text_empty`, which says so.
- R6. Chunks of about 1,200 characters with 200 characters of overlap, preferring paragraph and
  sentence breaks, with page and sequence. Re-running replaces the source's chunks, never adds to
  them. Each chunk copies the source's workspace and agent.
- R7. Statuses: `pending` → `processing` → `ready` or `failed`, with a fixed error code and text:
  `text_empty`, `text_unreadable`, `text_too_long`, `pages_too_many`, `processing_timeout`,
  `processing_failed`, `file_missing`.
- R8. Retries with exponential backoff (30 s, then 2 min) for failures that may pass (timeout,
  crash), at most 3 attempts; failures in the document itself are not retried.
- R9. A source deleted during processing stays deleted: its result is dropped.
- R10. No document text in logs or errors: the child's output is read only as data, its stderr is
  discarded, and log lines carry codes and ids only.

## Decisions and assumptions (owner away)

- **pypdf 7.2.0** (pure Python, maintained, no dependencies) for PDF text. DOCX is read with the
  standard library: the format is a ZIP of XML, and reading it ourselves lets us count real bytes.
- **A child process per document** (not a thread): only a process can be stopped when a parser
  hangs or loops. The worker handles one job at a time, which suits a low-memory machine.
- **The worker is a separate process** started next to the API (`python -m app.worker`); the API
  never processes. Development runs it by hand; tests call one worker step directly.
- **Chunk size** 1,200 characters with 200 overlap: a common default for retrieval; tunable later.
- **Chunks are stored now, embeddings come in Slice 4.3.** The storage cap still counts files only.
- **Failed sources stay listed** with their reason until someone deletes them; there is no
  "reprocess" action yet (delete and upload again).

## Review and end-to-end check

- **Found by the end-to-end check** (a real upload through the API, then the real `python -m
  app.worker`): the worker process loaded only some models, so every job failed with
  `NoReferencedTableError`. The tests import everything and could not see it. The worker now
  imports every model, and a test starts a fresh interpreter to prove it.
- **One independent Claude reviewer, reading only.** No P0. Fixed: P1, a source whose every
  attempt died with its worker stayed "processing" forever (the job now fails it); P2, the DTD
  check was a byte scan that UTF-16 passed (expat itself now refuses any DTD, and the DOCX is
  read as a stream without building a tree); P2, a failing sweep killed the worker; P2, the child
  had no memory cap (512 MB: `RLIMIT_AS` on POSIX, a watchdog thread on Windows). Fixed P3s: any
  parser error on a bad document is `text_unreadable`, not a retried crash; a worker whose lease
  ran out can no longer overwrite the one that took over; a source deleted before processing
  starts no longer causes a retry; a downgrade leaves sources to be processed again; three weak
  tests (a DTD test that failed for another reason, an archive whose sizes were honest, a give-up
  test that ignored the source).

## Tests

- Fixtures of each type produce the expected text, chunks, pages and sequence.
- Empty, scanned-like (no text layer), malformed, encrypted PDFs, and too many pages fail
  honestly; a too-long text fails; a stuck extraction is stopped by the timeout.
- A DOCX whose real unpacked XML is too large fails even when its directory claims small sizes;
  a DOCX with a DTD fails.
- Enqueueing twice makes one job; running a job twice keeps one set of chunks.
- Backoff and the attempt limit; an expired lease is taken over; a deleted source's result is
  dropped; a missing file fails as `file_missing`.
- The upload request does no processing; chunks carry the source's workspace and agent.
- No document text in logs, including when extraction crashes.
