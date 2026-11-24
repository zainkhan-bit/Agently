---
title: Dashboard Shell (Slice 1.4) - Plan
type: feat
date: 2026-11-24
topic: dashboard-shell
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Dashboard Shell (Slice 1.4) - Plan

## Goal Capsule

- **Objective:** A person who signs in lands on the dashboard of their workspace, always sees which workspace they are in, and can reach every signed-in page from there. This completes the Phase 1 exit gate.
- **Means:** one shared layout over the existing APIs (KTD1–KTD4).
- **Product authority:** `AGENT_BUILD_GUIDE.md` Slice 1.4 and Section 6, then this plan.
- **Execution profile:** one slice on `main`, one focused review (frontend and accessibility) before push.
- **Stop conditions:** a backend or schema change turns out to be needed.
- **Open blockers:** none.

---

## Product Contract

### Summary

A shared layout for signed-in pages: a left sidebar on laptop, and the same column behind a menu button on tablet and mobile. Sign-in opens the workspace last used in that browser. The dashboard shows real workspace data; Settings takes over the existing member list and delete.

### Problem Frame

Sign-in ends on an account page. The signed-in pages share no navigation, and Phase 2 has nowhere to put agents.

### Key Decisions

- **Open the last-used workspace, remembered in the browser.** (session-settled: user-directed — chosen over always the first, always choosing, and storing it on the server, which needs a migration.)
- **Summary cards plus an agents note without a button.** (session-settled: user-directed — chosen over cards only or the note only.)
- **Left sidebar.** (session-settled: user-directed — chosen over a top bar, which crowds at five sections, and bottom tabs, a second navigation pattern.)
- **Settings only moves what exists.** (session-settled: user-directed — chosen over adding rename or full member management.)
- **The remembered value is keyed by user id and holds only a workspace id.** (session-settled: user-directed — chosen over storing names or emails, which a shared browser would reveal.)

### Requirements

**Landing**

- R1. Sign-in and registration open the last-used workspace if the person still belongs to it, otherwise their first one, otherwise the create form.
- R2. Storage holds only a workspace id, keyed by user id. It survives sign-out and never grants access. Unavailable storage breaks nothing.
- R3. A link to a workspace the person cannot access shows "Workspace not found" without redirecting.
- R4. The home page shows "Go to dashboard" to a signed-in visitor.

**Layout**

- R5. All signed-in pages share the layout. Signed-out visitors go to `/login`; a server failure shows a retry, not a login redirect.
- R6. The sidebar holds a workspace switcher with "New workspace", links to Dashboard, Settings and Account, the account email and sign out.
- R7. Without any workspace, Dashboard and Settings links are absent, and account and sign out still work.
- R8. Below laptop width the sidebar is behind a menu button.

**Pages**

- R9. The dashboard shows the workspace name, the person's role and the member count from the API, and says agents are not available yet.
- R10. Settings shows members, and delete for owners only. Deleting lands per R1.
- R11. Loading, error with retry, and not-found states exist on every workspace page.

**Proof**

- R12. Automated accessibility checks and keyboard checks pass at mobile, tablet and laptop widths, with no horizontal scroll.
- R13. `PROJECT_STATUS.md` gets a "Phase 1 exit gate" section: each gate with its proof, and everything open before deployment.

### Scope Boundaries

- Deferred: returning to the page where a session ended, rename and other member management.
- Not built: agents, invitations, navigation for sections that do not exist.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **URLs.** `/workspaces/<id>` is the dashboard, `/workspaces/<id>/settings` is settings, `/dashboard` resolves R1 and redirects. The URL stays the only source of the active workspace.
- KTD2. **The layout re-reads the account and workspaces on each navigation**, so it reflects creates, deletes and a different sign-in from another tab. It writes the last-used value only for a workspace in that list.
- KTD3. **Pages still load their own workspace from the API**, which checks membership. The layout's list is never used as authorisation.
- KTD4. **Menu and switcher are disclosures, not modal dialogs or ARIA menus.** Ordinary links, Escape closes, focus is never left on a hidden element.

## Implementation Units

### U1. Landing and storage

- **Requirements:** R1, R2, R4
- **Files:** `frontend/src/lib/lastWorkspace.ts`, `frontend/src/features/workspaces/OpenDashboard.tsx`, `frontend/src/features/auth/{AuthForm,HomeNav}.tsx`, `frontend/src/app/{page.tsx,dashboard/}`
- **Test scenarios:** remembered, lost access, none remembered, no workspaces, throwing storage, per-user key, only an id stored, 401, network failure.

### U2. Layout

- **Requirements:** R5–R8
- **Files:** `frontend/src/features/shell/`, `frontend/src/app/(app)/`, `frontend/src/features/auth/SignOutButton.tsx`
- **Test scenarios:** links and current page, not-found workspace, no workspaces, refresh after navigation, failed refresh, 401, Escape and focus.

### U3. Dashboard and settings

- **Requirements:** R3, R9–R11
- **Files:** `frontend/src/features/workspaces/`
- **Test scenarios:** real values, no controls in the agents note, error and retry, not found, existing delete tests.

### U4. Browser checks and docs

- **Requirements:** R12, R13
- **Files:** `docs/manual-checks/`, `README.md`, `docs/SYSTEM_ARCHITECTURE.md`, `PROJECT_STATUS.md`, `.gstack/pregate.json`

## Verification Contract

| Gate | Command |
|---|---|
| Frontend | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` |
| Backend (unchanged, exit gate) | `.venv\Scripts\python -m pytest`, `ruff check .`, `ruff format --check .` |
| Browser | auth, workspace and dashboard checks through the real proxy |
| Review | one focused reviewer: frontend and accessibility |

## Definition of Done

- R1–R13 each have a passing test, browser check or documentation change.
- Review findings are fixed or recorded; verified commits are pushed.
