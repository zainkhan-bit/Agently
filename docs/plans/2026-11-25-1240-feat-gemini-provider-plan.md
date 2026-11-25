---
title: Provider Contract and Gemini Adapter (Slice 3.1) - Plan
type: feat
date: 2026-11-25
topic: gemini-provider
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Provider Contract and Gemini Adapter (Slice 3.1) - Plan

## Goal Capsule

- **Objective:** The server can make real drafts with Google Gemini, chosen by configuration, without surprise bills, leaked private text or an exposed key. Chat gets a streaming interface.
- **Product authority:** `AGENT_BUILD_GUIDE.md` Slice 3.1, `docs/MASTER_PRD.md` MDL-1 and MDL-2, the list "Before enabling a real provider key" in `PROJECT_STATUS.md`, then this plan.
- **Stop conditions:** the first real call, which needs the owner's yes after they see exactly what is sent; a settled decision that proves unworkable; an isolation test that would have to be weakened.
- **Open blockers:** the real-provider test waits for that yes.

---

## Product Contract

### Summary

A Gemini adapter, off by default, behind the interface the mock uses, with streaming added to both.
Every real call is paid for in advance from a server-wide budget and is cut off at a fixed time.
The describe page says who receives the answers before anyone types.

### Problem Frame

Drafts only work with a mock, so nobody knows whether real ones are usable.
A real key brings risks the mock never had: cost, private text leaving the server, and the key itself.

### Key Decisions

- **Gemini, not Anthropic, is the first adapter.** Governs R1. (session-settled: user-directed — chosen over the PRD's Anthropic default: the owner has a Gemini key.)
- **Free tier for development; production refuses it.** Governs R12, R13. (session-settled: user-directed — chosen over paid or unknown: on free, Google may use and review what people type.)
- **Dollar budget, reserved first and corrected after.** Governs R7 to R10. (session-settled: user-directed — chosen over a daily limit only or a call count: $1 a day and $10 a month limit money, not calls.)
- **All of the guide's items; the agent `model` field stays empty.** Governs R3 to R5. (session-settled: user-directed — chosen over per-agent models or deferring tool calls: chat is the first thing that would use a choice.)
- **Failed calls keep their reservation.** Governs R9. (session-settled: user-approved — chosen over refunds: Google may have charged for them.)
- **A notice without a checkbox.** Governs R12. (session-settled: user-approved — chosen over consent: telling people where they type was the agreed item.)
- **The key travels only in the `x-goog-api-key` header.** Governs R11. (session-settled: user-directed — chosen over `?key=`: URLs reach proxy logs and error messages.)
- **`gemini-3.5-flash-lite`, or the cheapest other allowed model if the key cannot use it.** Governs R5. (session-settled: user-directed — chosen over `gemini-3.8-flash` as default: cheaper and faster.)

### Requirements

**Interface**

- R1. `MODEL_PROVIDER=gemini` selects Gemini. No request can choose a provider, model, or limit.
- R2. The existing call is unchanged. Beside it, a stream gives text pieces and ends with one result that holds the whole text and the token counts.
- R3. Closing a stream cancels it.
- R4. The contract can represent tool calls. Nothing sends tools, and a tool call from Gemini is an error.
- R5. One server-wide model comes from a short allowed list that records its limits, prices and streaming support. Any other model stops startup, and a call above a model's limits is refused unsent.
- R6. A call ends by its deadline whatever the network does: slow name lookup, slow connection, or a trickle of bytes. There is no automatic retry.

**Spending**

- R7. All real calls share two configurable limits: $1 per 24 hours and $10 per 30 days, rolling.
- R8. The worst-case cost is reserved in the database before a call. If it does not fit a limit, or cannot be recorded, no call is made. Parallel calls cannot pass the limit together.
- R9. A successful call is corrected to its real cost. Every other outcome keeps the reservation.
- R10. A warning without private text is logged whenever spending is at or above 80% of either limit. The mock costs nothing.

**Privacy**

- R11. The key is only ever in the `x-goog-api-key` header: never in a URL, log, error, response or frontend file. Keys, prompts, answers and output are not logged, also at `LOG_LEVEL=DEBUG`.
- R12. With Gemini, the describe page says before anyone types: "Your answers are sent to Google Gemini. Google may use them to improve its products and people may read them. Don't include personal or confidential information." The paid tier leaves out the middle sentence.
- R13. The tier is a setting, free by default. Production refuses to start with Gemini on free.
- R14. If the page does not know which notice applies, nothing can be typed or generated. If the notice changed after the page loaded, the server refuses to send the answers, and the page shows the new notice and keeps them.

**Failures and tests**

- R15. A missing or malformed key stops startup with a message that names the setting. A key or model that Google refuses gives a distinct error. Timeout, rate limit, spending limit, refusal and other failures stay distinct.
- R16. Automated tests cannot use a real key or reach a network, whatever `backend/.env` says.
- R17. The real test is a script that shows the exact requests, and calls Google only when told to.

### Acceptance Examples

- AE1. **Covers R8.** Given room for one more call under the limit, when two arrive together, then one is sent and one gets the spending-limit error.
- AE2. **Covers R6.** Given a server that sends a little every 50 ms forever, then the call ends at its deadline.
- AE3. **Covers R11.** Given any call, then no URL contains the key and the header does.
- AE4. **Covers R14.** Given a page opened with the mock, when the server moves to Gemini and the person generates, then nothing is sent, the notice appears and the answers remain.

### Scope Boundaries

- Deferred: streaming on any page (3.4), per-agent models, sending tools, usage screens and per-user usage records, other providers.
- Not built, recorded as deployment blockers: Google's 18+ rule; the EEA, UK and Swiss rule that requires the paid tier; the AI Studio spend cap before the paid tier.

### Dependencies / Assumptions

- The limits rest on Google's token counts and our price list, read 2026-11-25. Promotional prices are ignored.
- Google's free rate limits may be reached before ours.
- If the tier setting is wrong, so is the notice.

### Sources / Research

Read 2026-11-25: Gemini API terms, pricing, models, deprecations, billing and thinking pages, and the v1beta discovery document. `gemini-3.5-flash-lite`: $0.30 in and $2.50 out per million tokens. `gemini-3.8-flash`: $1.50 and $7.50 from January 2027.

---

## Planning Contract

**Product Contract preservation:** the owner's three additions were applied before writing.

### Key Technical Decisions

- KTD1. **httpx, no SDK.** It is already a test dependency, and an SDK would add its own logging and retries. No environment proxies and no redirects, so the key goes to one host.
- KTD2. **A worker thread does the network work and the caller waits with a deadline.** Socket timeouts bound each read, not the whole, and an event loop would wait for a stuck name lookup when closing. Workers are capped, and a stuck one keeps its place.
- KTD3. **`complete` collects the same stream.** One wire path to secure.
- KTD4. **The budget wraps the adapter in selection**, so no caller can go round it. It uses its own short transactions and an advisory lock, and the time they take comes off the deadline.
- KTD5. **Costs are integer nano-dollars; the input bound is one token per UTF-8 byte** plus a margin per message. Thinking counts as output.
- KTD6. **Library loggers are switched off**, not just raised, and settings errors hide their input.
- KTD7. **`tests/__init__.py` forces the provider off before the app is imported**, and a fixture refuses non-loopback sockets.
- KTD8. **The page sends the notice it showed; the server compares it** before anything is counted.

---

## Implementation Units

### U1. Contract, models, mock streaming

- **Goal:** what chat needs, proven on the mock.
- **Requirements:** R2 to R5
- **Dependencies:** none
- **Files:** `backend/app/modules/providers/{contract,mock,models}.py`, `backend/tests/test_providers.py`
- **Test scenarios:** stream equals complete; close; failures; limits.

### U2. Gemini adapter

- **Goal:** one safe wire path.
- **Requirements:** R4, R6, R11, R15
- **Dependencies:** U1
- **Files:** `backend/app/modules/providers/gemini.py`, `backend/requirements.txt`, `backend/tests/test_gemini.py`
- **Test scenarios:** AE2, AE3; exact body; split bytes; every status and finish reason; nothing logged at DEBUG; abandoned and cancelled streams free their place.

### U3. Budget

- **Goal:** no call without money.
- **Requirements:** R7 to R10
- **Dependencies:** U1
- **Files:** `backend/app/modules/providers/{spending,tables}.py`, `backend/migrations/versions/0005_provider_spend.py`, `backend/tests/test_spending.py`
- **Test scenarios:** AE1 with real parallel connections; both windows; every failure keeps the reservation; warnings; database failure.

### U4. Settings, selection, notice

- **Goal:** safe configuration and honest disclosure.
- **Requirements:** R1, R12 to R16
- **Dependencies:** U2, U3
- **Files:** `backend/app/core/{config,logs}.py`, `backend/app/main.py`, `backend/app/modules/providers/selection.py`, `backend/app/modules/agent_builder/`, `backend/tests/`, `frontend/src/features/agents/`
- **Test scenarios:** AE4; startup refusals; every notice; unknown notice.

### U5. Real test, review, documents

- **Goal:** prove it, record it.
- **Requirements:** R17 and all
- **Dependencies:** U1 to U4
- **Files:** `backend/scripts/gemini_check.py`, `docs/`, `README.md`, `PROJECT_STATUS.md`
- **Test scenarios:** the script shows requests without calling; after the owner's yes, one draft and one stream.

---

## Verification Contract

| Gate | Command |
|---|---|
| Backend, zero skips | `backend: .venv\Scripts\python -m pytest`, `ruff check .`, `ruff format --check .`, `alembic check` |
| Frontend | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` |
| Browser check | `docs/manual-checks/builder-browser-check.js` with the mock |
| Guards are tested | break key guards one at a time and see a failure |
| Real provider | `scripts/gemini_check.py`, after the owner's yes |
| Repo gate | `/verify` right before commit |

## Definition of Done

- All units verified, security reviewed, `PROJECT_STATUS.md` updated with real results. The owner's `.env` is switched only after the real test passes.
