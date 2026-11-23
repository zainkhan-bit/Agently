---
title: Workspaces and Membership (Slice 1.3) - Plan
type: feat
date: 2026-11-23
topic: workspaces-and-membership
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Workspaces and Membership (Slice 1.3) - Plan

## Goal Capsule

- **Objective:** Every account has a private workspace, and no account can see or change another tenant's workspace or members. Later features build on that boundary.
- **Means:** one membership-resolving dependency for every workspace route, row locks for owner changes (KTD1–KTD4).
- **Product authority:** `AGENT_BUILD_GUIDE.md` Slice 1.3 and 5.1–5.2, PRD WS-1 to WS-4 and DATA-1, ADR-0001, then this plan.
- **Execution profile:** one slice, committed locally on `main`. Not pushed until the owner decides on `/ultrareview`.
- **Stop conditions:** a test would touch a database other than `agently_test` or `agently_migrations_scratch`, or a schema change turns out to be needed.
- **Open blockers:** none.

---

## Product Contract

### Summary

Registration creates a personal workspace. Users create, list, open, rename and delete workspaces. Owners list members, change roles and remove members; anyone can leave unless they are the last owner.

### Problem Frame

Accounts exist but own nothing. The Phase 1 exit gate requires proven tenant isolation before agents, chats and documents are added.

### Key Decisions

- **Nobody can be added to a workspace yet.** There is no email service, and adding by email reveals accounts. (session-settled: user-directed — chosen over invite links and add-by-email.)
- **404 for non-members, 403 for members who are not owners.** Governs R4, R5. (session-settled: user-approved.)
- **The current workspace is the id in the URL.** Nothing is stored in the session or cookie. Governs R4. (session-settled: user-approved.)
- **Account deletion is not built.** Its last-owner rule moves to the slice that adds it. (session-settled: user-approved.)
- **No data migration for accounts that have no workspace.** They use the create form. (session-settled: user-approved.)

### Requirements

**Workspaces**

- R1. Registration creates the user, a personal workspace, the owner membership and the session in one transaction. (WS-1)
- R2. A user can create workspaces and list only those they belong to, with their role in each. (WS-2)
- R3. Names are trimmed, 1 to 100 characters, without control characters.
- R4. Every route naming a workspace resolves the caller's own membership on the server. A non-member gets the same 404 as for a workspace that does not exist. (WS-3)
- R5. Renaming, deleting, changing roles and removing members need an owner. A member gets 403. (WS-4)
- R6. Deleting a workspace is immediate and permanent. Its users remain.
- R7. A user owns at most 20 workspaces, counting the personal one. Two parallel creates cannot make 21.

**Members**

- R8. Members of a workspace can list its members with email and role. Nobody else can.
- R9. An owner can promote, demote and remove members. A member can leave.
- R10. A workspace always keeps at least one owner. Leaving, removal and demotion of the last owner are refused with 409, including when requests run at the same moment.

**Proof**

- R11. A tenant isolation matrix generated from the registered routes: for every verb of every workspace and member endpoint, a signed-in outsider gets 404 with no tenant data, and nothing changes. New workspace routes are covered automatically.
- R12. A test fails when a route naming a workspace does not depend on the membership check.
- R13. Concurrent last-owner and 20-workspace tests run on separate database connections.

**Frontend and docs**

- R14. `/workspaces` lists and creates workspaces; `/workspaces/<id>` shows the name, role and members, and lets an owner delete it after typing its name. An unknown id shows "not found".
- R15. `PROJECT_STATUS.md` records the isolation matrix by name as Phase 1 exit-gate proof, and lists the `ENVIRONMENT` default under "Must fix before any deployment".

### Scope Boundaries

- Invitations, account deletion, member-management screens, dashboard layout and styling are not built.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **`get_workspace_context` is the only way to a workspace.** It depends on the current user and one query joining workspace and membership on both ids. The owner variant depends on it.
- KTD2. **Owner changes lock the workspace's owner memberships** with `SELECT … FOR UPDATE` in id order, after locking the workspace row so that waiting requests read a fresh owner list and cannot deadlock (added after review), then re-check the caller's role from the locked rows before acting. Every member mutation, rename and delete takes this lock first, so a caller demoted while waiting cannot act. Governs R5, R9, R10. (session-settled: user-directed — row lock chosen over an unlocked count.)
- KTD3. **The 20-workspace limit locks the user's row, then counts.** Locking existing memberships would not block a new insert. `FOR NO KEY UPDATE` is used so sign-ins, which reference the user row, are not blocked. Promotion to owner applies the same check. Governs R7.
- KTD4. **No migration.** The Slice 1.1 tables and cascades are sufficient.

## Implementation Units

### U1. Workspace service, dependencies and routes

- **Goal:** R1–R10 behind `/api/workspaces`.
- **Requirements:** R1–R10 (KTD1–KTD4)
- **Files:** `backend/app/modules/workspaces/{dependencies,service,schemas,router}.py`, `backend/app/modules/identity/service.py`, `backend/app/main.py`, `backend/tests/test_workspaces_api.py`
- **Approach:** thin routes; the service owns rules and commits.
- **Test scenarios:** registration creates one owned workspace; a failed registration leaves none; create, list, rename, delete; name bounds; member gets 403 on each owner action; a member cannot promote themselves; last-owner leave, removal and demotion give 409; handover works; a removed member gets 404; the limit counts the personal workspace.
- **Verification:** tests pass on `agently_test`.

### U2. Isolation matrix and concurrency proof

- **Goal:** R11–R13.
- **Requirements:** R4, R7, R10–R13
- **Files:** `backend/tests/test_tenant_isolation.py`, `backend/tests/test_workspace_concurrency.py`
- **Approach:** the matrix enumerates registered routes. Concurrency tests hold the contested lock, wait until both requests are blocked in PostgreSQL, then release it, so the race is certain rather than likely.
- **Test scenarios:** as R11–R13, for demote, remove and leave, and for parallel creates at 19.
- **Verification:** removing the lock, or the membership filter, makes the tests fail.

### U3. Pages, browser check and docs

- **Goal:** R14, R15.
- **Requirements:** R14, R15
- **Files:** `frontend/src/features/workspaces/*`, `frontend/src/app/workspaces/**`, `docs/manual-checks/workspace-browser-check.js`, `docs/DATABASE_DESIGN.md`, `docs/SYSTEM_ARCHITECTURE.md`, `README.md`, `PROJECT_STATUS.md`
- **Approach:** reuse `apiFetch`, `apiPost` and the loading, error and retry pattern of `AccountView`.
- **Test scenarios:** list, empty state, create, validation error, 401 to login, 404 message, delete enabled only by the exact name.
- **Verification:** frontend gates and the browser check pass.

## Verification Contract

| Gate | Command |
|---|---|
| Backend | `backend: .venv\Scripts\python -m pytest`, `ruff check .`, `ruff format --check .`, `alembic check` |
| Frontend | `frontend: npm test`, `npm run lint`, `npm run typecheck`, `npm run build` |
| Browser | `node "<playwright-skill dir>/run.js" docs/manual-checks/workspace-browser-check.js`, and the auth check again |
| Review | two focused reviewers: tenant isolation and access control; data and concurrency |

## Definition of Done

- R1–R15 each have a passing test, browser check or documentation change.
- Lock and isolation guards are mutation-checked.
- Review findings are fixed or recorded; the slice is committed locally and not pushed.
