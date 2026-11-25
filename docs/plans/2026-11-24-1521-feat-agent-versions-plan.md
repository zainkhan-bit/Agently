---
title: Agent Configuration and Versions (Slice 2.4) - Plan
type: feat
date: 2026-11-24
topic: agent-versions
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Agent Configuration and Versions (Slice 2.4) - Plan

## Goal Capsule

- **Objective:** Any member can see what an agent was configured with at each save, and safely go back to an earlier configuration.
- **Product authority:** `AGENT_BUILD_GUIDE.md` Slice 2.4, `docs/MASTER_PRD.md` AGT-4, ADR-0005, then this plan.
- **Execution profile:** one slice on `main` with one additive migration.
- **Stop conditions:** a settled decision proves unworkable, or an isolation test must be weakened.
- **Open blockers:** none. Recording a version on an execution is BLOCKED until executions exist (Phase 3).

---

## Product Contract

### Summary

Each agent gets a paged version history, a read-only view of any version, and a rollback.
Rollback saves a new version copied from the old one.

### Problem Frame

Every changing save already writes an immutable version, but no screen or API shows any version except the current one.
Undoing a bad edit means retyping up to 10,000 characters of instructions from memory.

### Key Decisions

- **Rollback creates a new version.** Governs R8, R9. (session-settled: user-directed — chosen over moving the current pointer back or rewriting: history stays true.)
- **The source of a rollback is stored.** Governs R10. (session-settled: user-directed — chosen over not recording it: it cannot be filled in later.)
- **Versions have unique ids in URLs.** Governs R19. (session-settled: user-approved — chosen over version numbers: numbers repeat across agents, so swapping them proves nothing.)
- **The matrix also attacks across agents in one workspace.** Governs R20. (session-settled: user-approved — chosen over workspace swaps only: those never try this.)
- **History is paged and names changed fields; the diff waits.** Governs R1, R3. (session-settled: user-directed — chosen over a full side-by-side diff.)
- **"Former member" instead of an email.** Governs R4. (session-settled: user-directed — chosen over showing who they were: no email after someone leaves.)
- **Rollback follows the rules of editing.** Governs R11, R12, R13, R14, R15. (session-settled: user-approved — chosen over special cases: rollback cannot get around an edit rule.)
- **The existing edit page is the guide's settings page.** Governs R17. (session-settled: user-approved — chosen over a second page: it already validates and warns about unsaved changes.)

### Requirements

**History**

- R1. Any member can list an agent's versions, newest first, 20 per page. Archived agents are included.
- R2. Each entry shows the version number, the name, when it was saved, who saved it, and whether it is current.
- R3. Each entry lists the names of the fields that differ from the version numbered one lower, also across a page boundary. Version 1 is shown as "Created".
- R4. The saver is shown by email only while they are a member of this workspace. Otherwise, including when their account is deleted, the entry says "Former member" and the server sends no email.
- R5. The list does not carry instructions text.
- R6. Any member can open one version and read its whole configuration. It cannot be edited there.

**Rollback**

- R7. Any member can roll back to any version that is not current, after a confirmation naming the version.
- R8. Rollback saves a new version holding every configuration field of the chosen one, name included, with the next number and the person who rolled back as saver.
- R9. No existing version is changed or deleted, and the agent's status does not change.
- R10. The new version permanently records which version it was copied from, and history shows "Restored from version N". Versions from edits, creation and duplication record none.
- R11. The request carries the version the person saw as current. If that is stale, it gets the existing 409 and saves nothing.
- R12. At 200 versions a rollback that would change something is refused with the existing limit error. The message for edits and rollbacks at the limit says that duplicating the agent is the way on.
- R13. An archived agent cannot be rolled back. It must be restored first.
- R14. Rolling back to a configuration equal to the current one saves nothing and succeeds, also at 200 versions.
- R15. A version that breaks today's field rules is refused with a clear error, and nothing is saved.
- R16. Rollback counts toward the existing agent write limit and uses the existing write timeouts.

**Screen**

- R17. Edit, its validation and its unsaved-changes warning stay as they are. Agent pages link to the history.
- R18. All text renders literally, and the pages meet Slice 2.2's accessibility, size and failure-message rules. A stale or busy rollback offers the latest state.

**Isolation**

- R19. Versions are addressed by unique ids. A version that is not of the agent in the path, or an agent not of the workspace, gets the same 404 as one that does not exist.
- R20. The isolation matrix, generated from the registered routes, attacks every route that names a version: from another tenant, from the caller's other workspace, and through another agent in the same workspace, in both directions. A new such route is covered without editing the tests, and a new path parameter without a real foreign object fails them.
- R21. Each attack leaves every table unchanged except throttle events, and a positive control shows that the rightful member reaches the same version.

### Key Flows

- F1. Undo a bad edit
  - **Trigger:** A member opens an agent's history.
  - **Steps:** They read the changed fields, open a version, choose to roll back and confirm. The agent shows the new current version.
  - **Covered by:** R1, R3, R6, R7, R8
- F2. Someone edits in between
  - **Trigger:** Another member saves after the history was opened.
  - **Steps:** The rollback gets 409. The member loads the latest state and decides again.
  - **Covered by:** R11, R18

### Acceptance Examples

- AE1. **Covers R8, R9, R10.** Given a paused agent with versions 1 to 5, when rolling back to 2, then version 6 equals 2 and says "Restored from version 2", versions 1 to 5 are identical to before, and the agent is still paused.
- AE2. **Covers R11.** Given two changing rollbacks sent at once with the same current version, then exactly one saves and the other gets 409.
- AE3. **Covers R12, R14.** Given 200 versions, then a changing rollback is refused, and one to an equal configuration succeeds and saves nothing.
- AE4. **Covers R3.** Given 21 versions where 20 and 21 differ only in name and instructions, then 21 lists exactly those two, and the last entry on page one is compared with the version on page two.
- AE5. **Covers R4.** Given a saver who was removed, then their entries say "Former member" and the response does not contain their email. If they join again, their email is shown again.
- AE6. **Covers R19, R20.** Given agents A and B in one workspace, then B's version id under A's path gets 404 for reading and for rollback, and the reverse.
- AE7. **Covers R15.** Given a stored version whose name breaks today's rules, then rolling back to it is refused and the version count is unchanged.

### Scope Boundaries

- Deferred: side-by-side diff, version labels, deleting or pruning versions, searching history.
- The model field stays empty until Slice 3.1. Rollback copies it like any other field.
- Existing versions have no recorded source, and none is invented for them.

### Dependencies / Assumptions

- R10 needs one schema migration.
- A permanent version id is what Phase 3 executions will point to. This slice cannot prove that they do.

### Sources / Research

- `backend/app/modules/agents/service.py`: locks, 409, version limit and the unchanged-edit rule.
- `backend/tests/test_tenant_isolation.py`: routes are found automatically, but `tenants` needs a real object per path parameter, and no attack crosses agents within one workspace.
- `backend/app/modules/workspaces/router.py`: the member list already shows emails to members.
- `docs/plans/2026-11-24-1020-feat-agent-data-model-and-apis-plan.md`: R6 and R12 to R17 of Slice 2.1.

---

## Planning Contract

**Product Contract preservation:** unchanged, except that the two questions deferred to planning are answered by KTD3 and KTD4 and were removed. The owner was away: KTD1 to KTD8 are the implementer's choices, and the assumptions are listed below.

### Key Technical Decisions

- KTD1. **The source is a version number with a composite foreign key to its own table** (`agent_id`, `restored_from` to `agent_id`, `number`), plus a check that it is lower than the new number. The database then refuses a source in another agent.
- KTD2. **One save path for edit and rollback.** Both lock, refuse archived and stale, compare, check the limit and write through the same functions, so the rules cannot drift apart.
- KTD3. **Pages continue from a version number (`before`), not an offset.** A version saved while paging shifts nothing. One extra row is read so that the last entry can be compared.
- KTD4. **A rollback is validated with the create schema.** Its stored values are copied, not the normalised ones. A failure is 409 `version_invalid` without the text of the version.
- KTD5. **The version is resolved by a dependency that builds on the agent one**, which builds on the membership one. The write throttle depends on it, so outsiders get 404 before anything is counted. The service looks the version up again inside the locks, by version and agent.
- KTD6. **The saver's email comes from an outer join on current membership of this workspace.** The response has no user id for the saver.
- KTD7. **The matrix swaps one parameter at a time with a sibling agent of the same workspace**, for every registered route with two or more object parameters. Collections are read and must not contain anything of the sibling.
- KTD8. **The history loads 20 entries and "Show older versions" adds 20 more**, like My Agents. Rollback asks with the browser's confirm dialog, like leaving unsaved text.

### Assumptions (owner away)

- Rolling back to a configuration equal to the current one says "Nothing changed" and stays on the page.
- After a rollback the agent page opens, as after an edit. It now shows the version number.
- Field names in history follow the form's order: name, purpose, description, instructions.

---

## Implementation Units

### U1. Stored source and version reads

- **Goal:** migration, list and single read.
- **Requirements:** R1 to R6, R10, R19
- **Dependencies:** none
- **Files:** `backend/migrations/versions/0004_agent_version_source.py`, `backend/app/modules/agents/`, `backend/tests/test_agent_versions.py`, `backend/tests/test_schema_constraints.py`
- **Test scenarios:** AE4, AE5; empty creator; stable pages; archived; no instructions in the list; the source constraint; deleting an agent that has sources.

### U2. Rollback

- **Goal:** a new version from an old one, by the rules of editing.
- **Requirements:** R7 to R16
- **Dependencies:** U1
- **Files:** `backend/app/modules/agents/`, `backend/tests/test_agent_versions.py`, `backend/tests/test_agent_concurrency.py`, `backend/tests/test_write_timeouts.py`
- **Test scenarios:** AE1, AE2, AE3, AE7; archived; throttle; races with edit, archive, delete and removal; locks released when nothing changes.

### U3. Isolation matrix

- **Goal:** every version route is attacked automatically.
- **Requirements:** R19 to R21
- **Dependencies:** U1, U2
- **Files:** `backend/tests/test_tenant_isolation.py`
- **Test scenarios:** AE6 in both directions; a planted route without the agent check is caught.

### U4. Screens

- **Goal:** history, version view, rollback.
- **Requirements:** R1 to R7, R10 to R15, R17, R18
- **Dependencies:** U1, U2
- **Files:** `frontend/src/features/agents/`, `frontend/src/app/(app)/workspaces/[id]/agents/[agentId]/versions/`
- **Test scenarios:** F1, F2; former member; literal text; every failure; no rollback for current or archived.

### U5. Proof and documents

- **Goal:** prove it and record it.
- **Requirements:** all
- **Dependencies:** U1 to U4
- **Files:** `docs/manual-checks/`, `.gstack/pregate.json`, `README.md`, `docs/DATABASE_DESIGN.md`, `docs/MASTER_PRD.md`, `PROJECT_STATUS.md`
- **Test scenarios:** the journey in a real browser; axe at each size.

---

## Verification Contract

| Gate | Command |
|---|---|
| Backend, zero skips | `backend: .venv\Scripts\python -m pytest`, `ruff check .`, `ruff format --check .` |
| Migration | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head` |
| Frontend | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` |
| Browser checks | all of `docs/manual-checks/` against a production build |
| Guards are tested | break key guards one at a time and see a failure |
| Review | one independent Claude reviewer, security and concurrency |
| Repo gate | `/verify` right before commit |

## Definition of Done

- All units verified, P0 to P2 findings fixed and P3s recorded, `PROJECT_STATUS.md` updated with real results, pushed.
