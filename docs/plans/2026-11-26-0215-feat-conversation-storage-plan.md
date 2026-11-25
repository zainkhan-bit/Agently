---
title: Conversation and Message Storage (Slice 3.2) - Plan
type: feat
date: 2026-11-26
topic: conversation-storage
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Conversation and Message Storage (Slice 3.2) - Plan

## Goal Capsule

- **Objective:** A private place to keep what one person and one agent said, showing which configuration produced each answer.
- **Product authority:** `AGENT_BUILD_GUIDE.md` Slice 3.2, `docs/MASTER_PRD.md` CHAT-1 and CHAT-3, ADR-0005, then this plan.
- **Execution profile:** one backend slice on `main` with one additive migration. No model calls, no screens.
- **Stop conditions:** an isolation test must be weakened, or message text cannot be kept out of logs.
- **Open blockers:** none.

---

## Product Contract

### Summary

Private conversations between one person and one agent. That person can start, list, read and delete them; to everyone else, teammates and owners included, they do not exist.
Storing messages is an internal operation that Slice 3.3 calls.

### Problem Frame

Agents can be configured but nobody can talk to them. The runtime (3.3) and the chat (3.4) need storage that is private to the person, leaves no trace in logs, and records the configuration behind each answer.

### Key Decisions

- **Only the creator sees a conversation.** Governs R2, R3. (session-settled: user-approved — chosen over creator plus owners, or all members: message text is private.)
- **Leaving or being removed deletes the person's conversations in that workspace at once.** Governs R11. (session-settled: user-approved — chosen over keeping them hidden: nobody could reach or delete them.)
- **Conversations are hard-deleted with their agent; usage rows survive.** Governs R10. (session-settled: user-directed — chosen over soft delete, ADR-0005.)
- **No route accepts messages in this slice.** Governs R5. (session-settled: user-approved — chosen over a public append: a client could forge replies.)
- **Size and rate limits.** Governs R7, R8, R9. (session-settled: user-directed — chosen over leaving them to planning.)

### Requirements

**Privacy and isolation**

- R1. A conversation belongs to one person, one agent and that agent's workspace. The database refuses any other combination.
- R2. Only its creator, while a member, can list, read or delete it. Everyone else, owners included, gets the same 404 as for an id that does not exist.
- R3. Every route goes through the membership check and joins the isolation matrix by itself. Teammates with either role attack every route that names a conversation. A new such route without the creator check fails the tests.
- R4. Message text never reaches the logs: not on a crash, not when the database rejects a row, not at `LOG_LEVEL=DEBUG`.

**Messages**

- R5. Messages are stored only by an internal operation. Roles are user and assistant; instructions are never stored as messages.
- R6. Every assistant message records the number of an existing version of the same agent; user messages record none. The database enforces both.
- R7. Each message has a sequence number, unique in its conversation and increasing by one, also under simultaneous writes. History is ordered by it.
- R8. A user message has at most 8,000 characters, an assistant message 32,000; blank text and invalid characters are refused. At most 500 messages per conversation. All configurable.
- R9. At most 200 conversations per person and agent, and 30 created per person and hour. Both configurable.

**Deletion and status**

- R10. Deleting a conversation, agent or workspace hard-deletes the messages with it.
- R11. Leaving, being removed, or deletion of the account deletes the person's conversations there.
- R12. Conversations of paused and archived agents can be read and deleted. New ones cannot be started.
- R13. Duplicating an agent copies no conversations. Nothing expires with age.

**Reading**

- R14. The list shows the newest activity first, in pages, with dates and message counts and no text.
- R15. History is read in pages from the newest backwards; each page is in order. It returns only role, text, sequence, version number and time.

### Key Flows

- F1. Someone starts a conversation, messages are stored, they read them page by page and delete the conversation. **Covered by:** R1, R7, R10, R14, R15

### Acceptance Examples

- AE1. **Covers R2, R3.** Given an owner and a member who are not the creator, when either uses the creator's conversation id on any route, they get the 404 of a missing id, nothing changes, and their own list does not contain it.
- AE2. **Covers R4.** Given a message insert that the database rejects, then neither the raised error nor the captured logs contain the text.
- AE3. **Covers R6.** Given an assistant message without a version, with a version the agent does not have, or a user message with a version, then it is refused.
- AE4. **Covers R7.** Given simultaneous writers, then the sequence has no gap and no duplicate.
- AE5. **Covers R11.** Given a removed person who is added again, then the old conversations are gone and other people's remain.
- AE6. **Covers R10.** Given an agent with conversations of several people and versions used by messages, when an owner deletes it, then all are gone and `provider_spend` is unchanged.

### Scope Boundaries

- Deferred: titles, search, rename, sharing, export, usage rows, any screen.
- Must be done before Slice 3.4 ships: warn owners that deleting an agent or removing a member deletes other people's private conversations.

### Sources / Research

- `backend/app/core/database.py`: `hide_parameters=True` is already set. It does not hide PostgreSQL's `Failing row contains (...)` detail, nor the result rows SQLAlchemy logs at DEBUG.
- `backend/app/core/errors.py`: unexpected errors are logged with their traceback, and the server logs them once more.

---

## Planning Contract

**Product Contract preservation:** unchanged. The KTDs are the implementer's choices.

### Key Technical Decisions

- KTD1. **The database ties ownership together.** `conversations` has composite foreign keys to `agents (id, workspace_id)` and `memberships (user_id, workspace_id)`, both cascading. Removal, leaving and account deletion therefore need no code that could be forgotten.
- KTD2. **`messages` carries `agent_id`** with composite keys to the conversation and to `agent_versions (agent_id, number)`. The version key cascades: with NO ACTION its check would run before the conversation's own cascade and block deleting the agent. Versions are only ever deleted with their agent.
- KTD3. **The conversation counts its messages.** The next sequence number is the count plus one, taken under the conversation's row lock. The unique constraint is the safety net and the index for "last N".
- KTD4. **Creating, storing and deleting lock like every other write** (workspace, membership, agent, then conversation), so they cannot deadlock with agent deletion or member removal.
- KTD5. **Database errors keep only PostgreSQL's primary message.** The detail is removed from both exceptions in the engine's error hook, before anything can log them.
- KTD6. **SQLAlchemy and psycopg loggers stay at WARNING or above**, whatever `LOG_LEVEL` is.
- KTD7. **One dependency resolves a conversation**: it builds on the agent one and filters by creator. A test requires it on every route with `conversation_id`.

### Assumptions (owner away)

- The creation limit answers 429, the cap 409 `conversation_limit`.
- The list uses limit and offset like the agent list, because there are at most 200 rows.
- Storing does not commit: Slice 3.3 decides what belongs together.

---

## Implementation Units

### U1. Log safety

- **Goal:** no path from a database error or DEBUG logging to message text in a log.
- **Requirements:** R4
- **Files:** `backend/app/core/database.py`, `backend/app/core/logs.py`, `backend/tests/test_private_text_logging.py`
- **Test scenarios:** AE2 through the production engine and through HTTP; DEBUG rows.

### U2. Schema

- **Goal:** tables that cannot hold an inconsistent conversation.
- **Requirements:** R1, R6, R7, R10, R11
- **Files:** `backend/app/modules/conversations/models.py`, `backend/migrations/versions/0006_conversations.py`, `backend/tests/test_conversations.py`
- **Test scenarios:** AE3, AE5, AE6.

### U3. Service and routes

- **Goal:** create, list, read, delete, and the internal storing operation.
- **Requirements:** R2, R5 to R9, R12 to R15
- **Dependencies:** U2
- **Files:** `backend/app/modules/conversations/`, `backend/app/modules/identity/throttle.py`, `backend/app/core/config.py`, `backend/tests/test_conversations.py`
- **Test scenarios:** AE4; limits, paging, status, throttle, races.

### U4. Isolation matrix

- **Goal:** teammates are attackers too.
- **Requirements:** R3
- **Dependencies:** U3
- **Files:** `backend/tests/test_tenant_isolation.py`
- **Test scenarios:** AE1; a planted route without the creator check is caught.

### U5. Proof and documents

- **Goal:** prove it and record it.
- **Files:** `.gstack/pregate.json`, `docs/decisions/ADR-0005-agent-deletion.md`, `docs/DATABASE_DESIGN.md`, `docs/SYSTEM_ARCHITECTURE.md`, `PROJECT_STATUS.md`

---

## Verification Contract

| Gate | Command |
|---|---|
| Backend, zero skips | `backend: .venv\Scripts\python -m pytest`, `ruff check .`, `ruff format --check .` |
| Migration | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head` |
| Guards are tested | break key guards one at a time and see a failure |
| Review | one independent Claude reviewer, privacy and isolation |
| Repo gate | `/verify` right before commit |

## Definition of Done

- All units verified, P0 to P2 findings fixed and P3s recorded, `PROJECT_STATUS.md` updated with real results, pushed to `main`.
