# Master PRD — Agently MVP

**Status:** v1 (locked for MVP build; changes recorded via ADR)
**Source:** `AGENT_BUILD_GUIDE.md` (no other product documents existed at audit time)

## 1. Roles

| Role | Scope | Can |
|---|---|---|
| Anonymous visitor | — | Register, sign in |
| Workspace **owner** | One workspace | Everything in the workspace, incl. delete workspace, manage members, approve sensitive tool actions |
| Workspace **member** | One workspace | Create/use agents, upload knowledge, chat; cannot permanently delete agents (ADR-0005), change roles or delete the workspace |

The permission model is a role → permission map on the server so new roles can be added later.

## 2. Primary user journey (MVP proof)

1. Register and sign in.
2. Create a private workspace (one is created automatically on registration).
3. Create an agent from a description or manually.
4. Review and edit the generated configuration.
5. Select an available model configuration.
6. Add private knowledge documents.
7. Test the agent in chat.
8. Agent answers using its instructions and relevant knowledge.
9. Inspect conversations, usage, and execution history.
10. Control the agent (pause/archive) and delete data.

## 3. Functional requirements and acceptance criteria

Each requirement is testable. IDs are referenced from tests and `PROJECT_STATUS.md`.

### Authentication (AUTH)
- **AUTH-1** Register with email + password. *AC:* valid input creates an account and a session; password is stored only as a strong hash; duplicate email returns a generic error that does not confirm the account exists beyond what registration inherently implies.
- **AUTH-2** Sign in / sign out. *AC:* wrong password and unknown email return the same error; sign-out invalidates the session server-side.
- **AUTH-3** Session retrieval. *AC:* `GET /api/auth/me` returns the user for a valid session, 401 for missing/expired/revoked sessions.
- **AUTH-4** Rate limiting. *AC:* repeated failed sign-ins from one IP/email are throttled with 429.

### Workspaces (WS)
- **WS-1** A workspace is created for a new user, who becomes owner. *AC:* membership row with role `owner` exists.
- **WS-2** List only workspaces the user is a member of. *AC:* User B never sees User A's workspace.
- **WS-3** Non-members cannot read/mutate a workspace. *AC:* 404 (not 403) for non-members to avoid confirming existence.
- **WS-4** Members cannot promote themselves. *AC:* role changes require owner.

### Agents (AGT)
- **AGT-1** Create/list/view/edit/duplicate/pause/archive/delete agents. *AC:* each operation except delete works for members; delete is for owners and members get 403 (ADR-0005); cross-workspace attempts return 404.
- **AGT-2** Validation. *AC:* empty/oversized names and instructions rejected with field-level errors.
- **AGT-3** Paused/archived agents cannot run. *AC:* chat returns a clear "agent paused" error.
- **AGT-4** Versioned configuration. *AC:* every save that changes something produces a version, up to 200 per agent; each execution records the version used; stale updates are rejected (optimistic concurrency). Members can view every version and roll back, which saves a copy as a new version and never changes history.
- **AGT-5** Prompt-to-agent builder. *AC:* produces a schema-validated *draft*; malformed model output is handled; generated drafts cannot enable tools or permissions; nothing saves without explicit user action.

### Models (MDL)
- **MDL-1** Provider-neutral interface with one real provider and a deterministic mock. *AC:* contract tests pass on the mock; real smoke test passes when a key is configured, otherwise BLOCKED.
- **MDL-2** Missing/invalid key, timeout, and rate-limit produce safe, actionable errors. Keys never appear in responses, logs, or the frontend bundle.

### Chat (CHAT)
- **CHAT-1** Conversations belong to one agent and workspace; cross-tenant IDs return 404.
- **CHAT-2** Streaming responses with sending/generating/completed/stopped/failed states.
- **CHAT-3** History persists across refresh; ordering is deterministic.
- **CHAT-4** Failed model calls do not create successful execution records; retries do not duplicate messages.

### Knowledge (KB)
- **KB-1** Upload TXT, PDF, DOCX (initial set) with size, extension, MIME, and signature validation; server-generated storage names.
- **KB-2** Async processing with visible status and honest failure reasons (no OCR claimed).
- **KB-3** Embeddings + retrieval filtered by workspace and agent at query time.
- **KB-4** Answers cite sources; retrieved text is labelled untrusted data; document prompt-injection cannot change permissions.
- **KB-5** Deleting a source removes file, chunks, and vectors.

### Memory (MEM)
- **MEM-1** Persistent memory is explicit, scoped, and user-inspectable/editable/deletable; disabled memory is never injected.

### Tools (TOOL)
- **TOOL-1** Central registry: id, schema, risk level, timeout, handler. Unknown/disabled tools never run; arguments validated server-side.
- **TOOL-2** One low-risk tool end-to-end.
- **TOOL-3** Sensitive tools need approval bound to exact arguments, with expiry; approvals are audited.

### Usage and activity (USE)
- **USE-1** Append-only usage ledger, idempotent on retry, unknown usage marked unknown (never fabricated).
- **USE-2** Execution history with states queued/running/waiting_approval/succeeded/failed/cancelled/timed_out.
- **USE-3** Configurable limits enforced before expensive work.

### Data control (DATA)
- **DATA-1** Users can delete agents, conversations, memories, knowledge sources, and workspaces; deletion behaviour is documented in `DATABASE_DESIGN.md`.

## 4. Non-functional requirements

- **Security:** server-side authorisation on every operation; tenant isolation tests are release blockers; secrets only from environment/encrypted storage.
- **Reliability:** timeouts and bounded retries on all network dependencies; health/readiness endpoints.
- **Performance:** paginated lists and histories; long work off the request path; streamed responses.
- **Accessibility:** semantic HTML, labels, keyboard operation, visible focus, contrast; responsive at mobile/tablet/laptop widths.
- **Observability:** structured logs with request/execution IDs; no secrets or full prompts/documents in logs.
- **UX states:** loading, empty, populated, validation error, network error with retry, permission denied, disabled resource.

## 5. Explicit exclusions (MVP)

Local desktop agent; arbitrary shell/terminal execution; visual workflow editor; multi-agent orchestration; public marketplace/sharing; large integration catalogue; model training; enterprise SSO/SCIM/compliance; production billing and payment collection.

The MVP journey (Section 2) depends on none of these.

## 6. Open questions (non-blocking)

| # | Question | Needed by | Current assumption |
|---|---|---|---|
| Q1 | Which model provider/key will be used for real-provider tests? | Phase 3.1 | Google Gemini (ADR-0006) |
| Q2 | Email delivery service for verification/password reset? | Post-MVP | Not built; not faked |
| Q3 | Production hosting target? | Phase 6.5 | Container-friendly; documented later |
