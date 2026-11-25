---
title: Runtime Service Without Tools (Slice 3.3) - Plan
type: feat
date: 2026-11-26
topic: agent-runtime
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Runtime Service Without Tools (Slice 3.3) - Plan

## Goal Capsule

- **Objective:** A person's message gets an answer from their agent's own instructions, stored once, with an honest record of what happened.
- **Product authority:** `AGENT_BUILD_GUIDE.md` 4.6 and Slice 3.3, `docs/MASTER_PRD.md` AGT-3, AGT-4, CHAT-4, USE-2, ADR-0005, ADR-0006, then this plan.
- **Execution profile:** one backend slice on `main`, one additive migration, the mock only.
- **Stop conditions:** message text cannot be kept out of logs, or a retry can duplicate a message.
- **Open blockers:** the real-provider runtime check is BLOCKED until the owner agrees to real calls.

---

## Product Contract

### Summary

Sending a message stores it, asks the model with the agent's current version and recent history, and stores the answer with that version.
Every attempt leaves a record without text: model, version, duration, tokens, result.

### Problem Frame

Conversations can be stored but nothing answers. A model call is slow, costs money and can fail, so retries and crashes must neither duplicate messages nor look like success.

### Key Decisions

- **Instructions stay in the system role; user messages are untrusted and delimited.** Governs R2, R3. (session-settled: user-directed — chosen over one mixed prompt: what a person types must not become instructions.)
- **Recent history within a token budget.** Governs R4. (session-settled: user-directed — chosen over the whole conversation: cost and limits.)
- **Every call goes through the spending limits and the deadline.** Governs R8. (session-settled: user-directed — chosen over a separate path: no unpaid or endless calls.)
- **The client names each message with a random id, so repeating a request cannot duplicate it.** Governs R6, R7. Recommended option taken while the owner was away, over comparing text.
- **The message is stored before the call, the answer after it.** Governs R5. Recommended option taken, over storing both at the end: a failed call must not lose what the person typed.
- **Messages that were never answered are left out of later prompts.** Governs R4. Recommended option taken, over keeping them: a text the provider refuses would otherwise block the conversation for good.

### Requirements

**Prompt**

- R1. The answer uses one version of this agent: the current one when the message is accepted. The stored answer and the record name it.
- R2. The agent's name, purpose and instructions are in the system message, after fixed rules. Nothing a user typed is ever in it.
- R3. Each user message is escaped inside `<user_message>` tags that it cannot close. An exact snapshot test holds the prompt.
- R4. History is the newest answered exchanges of this conversation, at most 20 messages, as many whole exchanges as fit the token budget. Instructions and the new message always come first; if they alone do not fit, the message is refused before it is stored.

**Running**

- R5. The user's message is stored before the call, the answer after it. No lock and no database connection is held during the call.
- R6. The same request id never stores a second user message and never starts a second call while one runs or after one succeeded. A finished one returns the stored answer. With other text it is refused.
- R7. After a failure the same request id tries again, only while its message is still the last one.
- R8. Calls use the configured provider with its spending limits, the existing deadline, and an output limit. No retries by the server. Paused and archived agents, missing providers, an outdated data notice, rate limits and full conversations are refused before the call.
- R9. One answer at a time per conversation, enforced by the database. A run that a crash left behind stops blocking after a grace period, and its late answer is dropped.
- R10. Closing the stream of a run cancels it: no answer is stored.
- R11. An answer that is blank, too long or has invalid characters is a failure.

**Records and privacy**

- R12. Every attempt has an execution record: status running, succeeded, failed, cancelled or timed_out; model, version, duration, tokens when known, and a fixed error code. It holds no text. Unknown tokens stay empty.
- R13. Only a stored answer makes a record succeeded, and the database refuses any other combination.
- R14. Records are deleted with their conversation, agent or workspace. `provider_spend` stays.
- R15. No message text, instructions or provider text in logs or errors.
- R16. The new route requires the creator and joins the isolation matrix. Clients cannot choose role, version, model or provider.
- R17. At most 60 messages per person and 200 per workspace and hour, configurable. Refused attempts by outsiders do not count.

### Key Flows

- F1. Send and answer. **Covered by:** R1 to R5, R12, R13
- F2. The call fails; the person repeats the same request; one user message and one answer exist. **Covered by:** R6, R7, R12
- F3. The connection drops after the answer was stored; the repeat returns it without a call. **Covered by:** R6

### Acceptance Examples

- AE1. **Covers R1.** Given an edit saved during the call, then the answer records the version the call used.
- AE2. **Covers R2, R3.** Given a message that closes the tag and claims to be the system, then the system message is unchanged and the text stays inside its tag.
- AE3. **Covers R6.** Given two simultaneous requests with one id, then one call is made and one gets 409.
- AE4. **Covers R9.** Given a conversation deleted, or a person removed, during the call, then nothing is stored and the answer is 404.
- AE5. **Covers R12.** Given a timeout, a refusal, a rate limit, or malformed output, then the record says timed_out or failed with its code, and no assistant message exists.
- AE6. **Covers R1.** Given two agents in one workspace, then neither prompt contains anything of the other.

### Scope Boundaries

- Deferred: streaming to the browser and any screen (3.4), tools, knowledge, memory, a history of executions on screen, usage rows, choosing a model per agent, summarising old history.
- BLOCKED: a check with the real provider.

### Sources / Research

- `backend/app/modules/providers/contract.py`: streams, errors, closing cancels.
- `backend/app/modules/agent_builder/`: escaping, slots, disclosure and error handling to follow.
- `backend/app/modules/conversations/service.py`: storing and locking.

---

## Planning Contract

**Product Contract preservation:** unchanged. The owner was away: recommended options were taken and are listed as decisions or assumptions.

### Key Technical Decisions

- KTD1. **A separate module `runtime`.** The route validates and calls; the service owns the lifecycle; `prompt.py` owns the prompt.
- KTD2. **The core is a generator over `Provider.stream`.** It yields pieces and ends with the stored answer. The JSON route drains it; 3.4 streams it. Closing it cancels.
- KTD3. **`messages.request_id`**, set for user messages, unique per conversation, returned in history so that a reloaded page can repeat a failed message. Existing rows keep none.
- KTD4. **`executions`** refers to the user message and the answer by conversation and sequence (cascading), and to the version. A partial unique index allows one running row per conversation; a check ties succeeded to an answer.
- KTD5. **Two short transactions.** The first locks like every write, decides, stores the message and the running record. The second locks again, checks that the record is still running, and stores the answer and the result together.
- KTD6. **Tokens are estimated as a third of the bytes plus a fixed overhead.** The default budget of 32,000 holds the longest instructions and message in any script. The spending limit has its own, stricter estimate.
- KTD7. **The disclosure check moves to the provider module**, because chat needs the same one.
- KTD8. **The mock answers chat prompts** deterministically from the last user message and gains a `refused` scenario.

### Assumptions (owner away)

- An abandoned run blocks its conversation for the provider timeout plus 60 seconds.
- Output limit 4,000 tokens, thinking included; a cut-off answer is stored as it is.
- An agent paused during a call does not discard the answer already being made.
- If the database is too busy to store an answer, the answer is lost and the person can repeat the message.
- A failed attempt counts toward the rate limit, and so does a repeat.

---

## Implementation Units

### U1. Prompt

- **Goal:** the exact messages, bounded.
- **Requirements:** R1 to R4
- **Files:** `backend/app/modules/runtime/prompt.py`, `backend/tests/snapshots/runtime_prompt.txt`, `backend/tests/test_runtime_prompt.py`
- **Test scenarios:** snapshot; AE2; pairs, budget and count limits; unanswered messages left out.

### U2. Records

- **Goal:** tables that cannot claim a false success.
- **Requirements:** R6, R9, R12 to R14
- **Files:** `backend/app/modules/runtime/models.py`, `backend/app/modules/conversations/models.py`, migration `0007`, `backend/tests/test_runtime.py`

### U3. Runtime and route

- **Goal:** the lifecycle.
- **Requirements:** R5 to R11, R15 to R17
- **Dependencies:** U1, U2
- **Files:** `backend/app/modules/runtime/`, `backend/app/modules/providers/`, `backend/app/modules/identity/throttle.py`, `backend/app/core/config.py`, `backend/tests/test_runtime.py`, `backend/tests/test_tenant_isolation.py`
- **Test scenarios:** F1 to F3, AE1, AE3 to AE6, every mock scenario, limits, logs.

### U4. Proof and documents

- **Files:** `.gstack/pregate.json`, `docs/AI_RUNTIME.md`, `docs/DATABASE_DESIGN.md`, `docs/SYSTEM_ARCHITECTURE.md`, `PROJECT_STATUS.md`

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

- All units verified, P0 to P2 findings fixed and P3s recorded, the real-provider check marked BLOCKED, `PROJECT_STATUS.md` updated with real results, pushed to `main`.
