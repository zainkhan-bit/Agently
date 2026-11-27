# Slice 4.1 — Secure upload and source records

- **Date:** 2026-11-27 (owner away, working autonomously; doc review skipped by instruction)
- **Goal:** a member uploads a PDF, DOCX, TXT or Markdown file to an agent; the server checks it
  by its content, stores it privately under a random name, and keeps a source record. List,
  status and delete APIs. Nothing reads the text yet (Slice 4.2).
- **Sources:** `AGENT_BUILD_GUIDE.md` Slice 4.1, `docs/MASTER_PRD.md` KB-1 and KB-5, the owner's
  brief (audit item 5.3), ADR-0005.
- **Stop conditions:** an isolation test would have to be weakened, or a file could be reached
  through a path the client controls.

## Requirements

- R1. Allowed types: PDF, DOCX, TXT, Markdown. Anything else is refused (415), SVG and HTML
  included, whatever the extension says.
- R2. The type comes from the content. The extension and the declared `Content-Type` must agree
  with it, or the file is refused.
  - PDF: starts with `%PDF-`, ends with `%%EOF` (last 1 KB). Refused when it names `/JavaScript`
    or `/Launch` (a heuristic: compressed objects can hide them; the file is never served).
  - DOCX: a ZIP with `[Content_Types].xml` and `word/document.xml`; no macros
    (`vbaProject.bin`), no encrypted entries, at most 2,000 entries, at most 100 MB unpacked and a
    ratio of at most 100 per entry (zip bombs). Nothing is unpacked to disk.
  - TXT and Markdown: strict UTF-8 (a BOM is allowed), no NUL or other control characters except
    tab, line feed, carriage return and form feed, and not starting with markup (`<!doctype`,
    `<html`, `<svg`, `<?xml`, `<script`, `<head`, `<body`, `<iframe`).
- R3. Size: at most `KNOWLEDGE_MAX_FILE_BYTES` (10 MB). A `Content-Length` above it is refused
  before anything is read; without one, 411. The body is counted while it is read too.
- R4. Storage: `KNOWLEDGE_STORAGE_DIR` (default `backend/var/knowledge`, ignored by git). Refused
  anywhere else inside the repository: there it could be served, run, or committed to this public
  repository. The stored name is 32 random hex characters, checked by the database
  and again before any path is built. The person's file name is only shown, never used as a path.
  Files are created exclusively, with mode 0600 where the OS supports it.
- R5. Per-workspace cap `KNOWLEDGE_STORAGE_LIMIT_PER_WORKSPACE_BYTES` (200 MB), checked under the
  workspace lock; at most `KNOWLEDGE_SOURCES_PER_AGENT` (100) sources per agent.
- R6. Upload rate limit: 30 per person and 100 per workspace per hour, counted after the access
  check, refused uploads included.
- R7. Source record: workspace, agent, who uploaded it, shown name, type, size, SHA-256, stored
  name, status (`pending` until Slice 4.2), error code, timestamps. The same content twice for one
  agent is refused (409).
- R8. APIs under `/workspaces/{id}/agents/{agent_id}/sources`: upload (POST), list (GET), status
  (GET `/{source_id}`), delete (DELETE `/{source_id}`). No download route.
- R9. Deleting a source, its agent or its workspace removes the file. A file left behind by a
  crash is removed by a sweep (`scripts.sweep_knowledge_files`), only when it is older than an hour
  and has no record.
- R10. File contents and file names are never logged; refusals log a fixed code only.
- R11. Every new route is in the isolation matrix, with a real source of the other tenant.

## Decisions and assumptions (owner away)

- **Sources are shared by the workspace,** like agents: every member can upload, list and delete
  them (MASTER_PRD roles table: members "upload knowledge"). They are not private like
  conversations. `source_id` joins the matrix's shared parameters.
- **The file is the raw request body,** not multipart: `Content-Type` is the file's type and the
  name is percent-encoded in an `X-File-Name` header (not the URL, which access logs print). The body can then be counted while it is read, and no multipart
  parser spools an unchecked file first. The frontend sends `fetch(url, {body: file})`.
- **No download route** in this slice: nothing to leak across workspaces and no stored file is
  ever served to a browser. Retrieval quotes chunks later (Slice 4.4).
- **Uploads to archived agents are refused;** paused agents accept them (pausing stops answers,
  not editing). Deleting is always allowed.
- **No interface in this slice:** the guide puts "inspect and remove knowledge sources" in 4.4.
  The APIs are complete and tested.
- **Status values** are fixed now (`pending`, `processing`, `ready`, `failed`) so that 4.2 needs
  no constraint change; 4.1 only sets `pending`.

## Review (one independent Claude reviewer, reading only)

No P0. Fixed: an upload held a pooled connection idle in a transaction while its body arrived
(P1: the rate-limit count now commits first); file names reached the access log through the query
string (P2: now a header). Fixed P3s: the commit-failure test never reached the code it named; no
test sent a body over the app-wide 64 KB; a corrupt DOCX entry gave 500; the storage-folder guard
allowed most of the repository; `/JS` followed by a line break passed the PDF heuristic. Recorded
P3s: body chunks are written on the event loop (small, bounded writes); a commit that fails after
the server committed would leave a record without its file (rare, ambiguous); the DOCX limits
trust sizes the archive declares, so Slice 4.2 must count the bytes it really unpacks.

## Tests

- Valid fixtures of each type are stored; record and file match; the name is random.
- Refused: oversized (by header and while reading), no length, empty, unsupported extension,
  extension/content mismatch, declared type mismatch, SVG and HTML (as `.txt`, `.md`, `.svg`),
  PDF with JavaScript, truncated PDF, DOCX with macros, encrypted entry, zip bomb, binary text,
  bad UTF-8, path-like names. Nothing is stored and no file is left behind.
- Cap, count limit, duplicate, rate limits, archived agent.
- Delete removes record and file; agent and workspace deletion remove files; the sweep removes
  old orphans only.
- Isolation matrix with sources; a source of another agent or workspace is 404.
- Logs carry neither file names nor content.
