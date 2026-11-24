---
title: My Agents Interface and Write Timeouts (Slice 2.2) - Plan
type: feat
date: 2026-11-24
topic: my-agents-interface
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# My Agents Interface and Write Timeouts (Slice 2.2) - Plan

## Goal Capsule

- **Objective:** Members manage their workspace's agents in the browser, screens never show a change the server did not confirm, and a stuck write clears itself.
- **Product authority:** `AGENT_BUILD_GUIDE.md` Slice 2.2, `docs/MASTER_PRD.md` AGT-1 and AGT-2, ADR-0005, then this plan.
- **Execution profile:** one slice on `main`, no schema change, one focused frontend and accessibility review before push.
- **Stop conditions:** a settled decision proves unworkable, or an isolation test must be weakened.
- **Open blockers:** none.

---

## Product Contract

### Summary

A My Agents area in each workspace: a list, a page per agent holding every action, and one form for creating and editing.
Agent and workspace writes give up after waiting 5 seconds for a lock, and the database ends one left idle mid-transaction.

### Problem Frame

Slice 2.1 gave members a complete agent API but no screen, and the dashboard says agents cannot be created.
Agent and workspace writes share locks with no timeout, so one stuck request blocks a workspace indefinitely.
A lock timeout alone does not fix this: it fails the waiters while the holder keeps its lock.

### Key Decisions

- **Waiters time out and idle holders are ended.** Governs R18, R19. (session-settled: user-directed — chosen over lock_timeout only: the workspace must recover.)
- **Workspace writes use the same helper.** Governs R18. (session-settled: user-directed — chosen over agent writes only: a stuck workspace action would still block agents.)
- **Actions sit on the agent page only.** Governs R3. (session-settled: user-directed — chosen over split or row actions: one place for errors and confirmations.)
- **One full form, with an unsaved-changes warning.** Governs R6, R11. (session-settled: user-directed — chosen over waiting for 2.4: losing 10,000 characters is too painful.)
- **User text is plain text.** Governs R15. (session-settled: user-directed — chosen over markdown rendering: audit 5.2.)
- **Live counter and client-side limit for instructions.** Governs R8. (session-settled: user-directed — chosen over server errors only: the person sees the limit while typing.)
- **Conflicts never merge or overwrite.** Governs R10. (session-settled: user-approved — chosen over last save wins: nobody's work is lost.)
- **No search.** (session-settled: user-approved — chosen over a filter: at most 50 agents by default.)

### Requirements

**Screens**

- R1. The sidebar links to My Agents in the active workspace, and the dashboard shows the real number of agents that are not archived.
- R2. The list shows name, purpose and status in words, with separate current and archived views, useful empty states, and every agent reachable however many there are.
- R3. The agent page shows the saved configuration and every action: edit, duplicate, pause or resume, archive or restore, delete.
- R4. Only actions valid for the status are offered; delete is offered to owners only, requires typing the name, and says what is removed.
- R5. Status text does not imply that agents can run yet.

**Form**

- R6. One form creates and edits name, purpose, description and instructions.
- R7. Errors appear beside their field and focus moves to the first one; typed text survives every failure.
- R8. Instructions show a live character count against 10,000, and the form cannot be submitted over the limit, counting as the server counts.
- R9. A second submit while one is pending sends nothing.
- R10. When someone else saved first, the text stays and the latest version can be opened, or loaded after confirming that the text is discarded.
- R11. Leaving with unsaved text asks first: closing or reloading, in-app links, Back, sign out, and the redirect after a session ends. Nothing is stored as a draft.

**Truthful state**

- R12. Nothing changes on screen before the server confirms, and then it shows what the server returned.
- R13. A failed action shows why. If the answer never arrived, the message says the change may have happened.
- R14. An agent outside the workspace in the URL looks the same as one that does not exist.
- R15. Name, purpose, description and instructions always render as literal text.
- R16. Every page handles loading, empty, error with retry, missing and signed-out states, at phone to laptop widths, by keyboard, without accessibility violations.
- R17. The delete-workspace warning says agents are deleted too.

**Timeouts**

- R18. Agent writes and workspace writes (create, rename, role change, removal, leave, delete) wait at most 5 seconds for a lock, and the database ends their transaction after 30 idle seconds; both are configurable.
- R19. Either case returns 503 with code `busy` and says nothing was changed; other database errors are unaffected.

### Acceptance Examples

- AE1. **Covers R15.** Given `<script>` and `<img onerror>` saved in every field, then every screen shows them literally and nothing runs.
- AE2. **Covers R12, R13.** Given an active agent, when pausing fails, then it still shows active, with the reason.
- AE3. **Covers R10.** Given an edit from version 1 while version 2 exists, when saved, then nothing is saved and the text remains.
- AE4. **Covers R14.** Given another workspace's agent id in the URL, then the page says the agent was not found and shows none of it.
- AE5. **Covers R18, R19.** Given a lock held by another transaction, when any listed write arrives, then it returns 503 after the timeout and changes nothing.
- AE6. **Covers R18, R19.** Given a write stalled while holding its locks, then the database ends it, a following write succeeds, and the stalled one returns 503 unsaved.

### Scope Boundaries

- Deferred to 2.3: prompt builder. Deferred to 2.4: version history and rollback.
- Not included: search, drafts, row actions, chat, model choice.
- One very long query is not covered by either timeout; these writes have none.

### Dependencies / Assumptions

- The lock timeout applies to each lock separately, so a write that waits for several can take longer than 5 seconds in total.

---

## Planning Contract

**Product Contract preservation:** the owner's four additions were applied before writing.

### Key Technical Decisions

- KTD1. **Transaction-local `set_config` in one helper, called where the workspace lock is taken.** Every covered write except workspace create already starts there. It ends with the transaction, so pooled connections do not keep it and reads are unaffected.
- KTD2. **One handler for SQLSTATE 55P03 and 25P03.** Anything else is re-raised to the existing 500 handler.
- KTD3. **The unsaved guard is one module flag plus one hook:** `beforeunload`, a capture click listener for same-origin links, and a duplicate history entry so Back can be asked about. Next.js cannot block navigation in general. Sign out and the shell's session redirect ask the same flag.
- KTD4. **Limits count code points**, as Python does.
- KTD5. **The archived view is a URL query**, so a refresh keeps it.
- KTD6. **Action buttons use `aria-disabled` and a ref guard while pending**, so keyboard focus is kept.

---

## Implementation Units

### U1. Write timeouts

- **Goal:** stuck writes clear themselves.
- **Requirements:** R18, R19
- **Dependencies:** none
- **Files:** `backend/app/core/{config,database,errors}.py`, `backend/app/modules/workspaces/service.py`, `backend/.env.example`, `backend/tests/test_write_timeouts.py`
- **Test scenarios:** AE5 for every write; AE6; reads and the next transaction have no timeout; another database error stays 500.

### U2. List, agent page and navigation

- **Goal:** see and manage agents.
- **Requirements:** R1 to R5, R12 to R17
- **Dependencies:** none
- **Files:** `frontend/src/features/agents/`, `frontend/src/app/(app)/workspaces/[id]/agents/`, `frontend/src/features/{shell,workspaces}/`
- **Test scenarios:** AE1, AE2, AE4; each state's actions; member without delete; empty, archived and more-than-one-page lists; unknown outcome wording.

### U3. Form and unsaved guard

- **Goal:** create and edit without losing text.
- **Requirements:** R6 to R11
- **Dependencies:** U2
- **Files:** `frontend/src/features/agents/`, `frontend/src/lib/`, `frontend/src/features/auth/SignOutButton.tsx`, `frontend/src/features/shell/AppShell.tsx`
- **Test scenarios:** AE3; counter with emoji at the limit and one past it; focus on the first error; double submit; each way of leaving, accepted and refused; no warning when clean or saved.

### U4. Browser checks, review and documents

- **Goal:** prove it in a browser and record it.
- **Requirements:** all
- **Dependencies:** U1 to U3
- **Files:** `docs/manual-checks/`, `.gstack/pregate.json`, `README.md`, `docs/DATABASE_DESIGN.md`, `PROJECT_STATUS.md`
- **Test scenarios:** the whole journey, AE1, AE3 and AE4 in a real browser; axe at each size; Back with unsaved text.

---

## Verification Contract

| Gate | Command |
|---|---|
| Backend, zero skips | `backend: .venv\Scripts\python -m pytest`, `ruff check .`, `ruff format --check .` |
| Frontend | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` |
| Browser checks | every check in `docs/manual-checks/` against a production build |
| Guards are tested | break key guards one at a time and see a failure |
| Repo gate | `/verify` right before commit |

## Definition of Done

- All units verified, review findings fixed or recorded, `PROJECT_STATUS.md` updated with real results, pushed.
