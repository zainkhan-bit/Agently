# Project Status — Agently

**Current milestone:** Phase 2 — Agent creation and configuration (Phase 1 exit gate met)
**Next smallest task:** Slice 3.1 — Provider contract and configuration (not started, waiting for the owner)

## Must fix before any deployment

- Run uvicorn with `--no-proxy-headers`, and put an edge proxy that appends to `X-Forwarded-For` in front (see Slice 1.2).

## Before enabling a real provider key

All of these, agreed with the owner on 2026-11-24:

- Tell users, where they type their answers, that the answers go to an outside provider.
- Set a spending cap on the provider account.
- Run the real-provider test (guide 2.3: a valid draft from a real provider). BLOCKED until a key exists.
- Give the adapter a hard deadline that it cannot exceed. The service passes a timeout but cannot stop a call.
- Add a server-wide spending limit. The per-user and per-workspace limits do not stop someone with many accounts.
- Stop provider and HTTP libraries from logging request text, also at `LOG_LEVEL=DEBUG`.

## Blocked / needs owner input

- ~~Slice 1.1 blocked on local PostgreSQL credentials~~ — resolved 2026-11-21: `GET /api/health/ready` returns `database: ok`.
- **Known gap (owner: the slice that adds account deletion):** it must refuse to delete a workspace's last owner, or transfer or delete the workspace first, with tests. Slice 1.3 enforces this for leaving, removal and demotion; account deletion does not exist in the app yet. Lock order and edge cases: `docs/DATABASE_DESIGN.md`.
- A real model-provider API key is needed for real-provider tests (Slices 2.3 and 3.1). Until then they are BLOCKED and a mock provider is used.

## Phase 1 exit gate

Checked 2026-11-24, after Slice 1.4. **All three gates pass locally.** There is no CI yet, so nothing re-runs these automatically.

| Gate (`docs/ROADMAP.md`) | Result | Proof |
|---|---|---|
| Secure login | PASS | `backend/tests/test_auth_api.py`, `test_auth_throttling.py`, `test_origin_guard.py`, `test_route_inventory.py`; `docs/manual-checks/auth-browser-check.js` (22) |
| Workspace dashboard | PASS | `frontend/src/features/shell/AppShell.test.tsx`, `frontend/src/features/workspaces/landing.test.tsx`; `docs/manual-checks/dashboard-browser-check.js` (91) |
| Isolation tests pass | PASS | `backend/tests/test_tenant_isolation.py` (46), `test_workspace_concurrency.py`; `docs/manual-checks/workspace-browser-check.js` (15) |

**Still open before any deployment**

Must fix:

- No edge proxy: uvicorn needs `--no-proxy-headers` and a proxy that appends to `X-Forwarded-For`, or all users share one throttling bucket. The client-IP source stays **Suspected** (audit 6.1) until a hosting target is chosen.
- The pre-launch security audit has not been run (owner starts it).
- No CI, deployment instructions, backups or monitoring (Phase 6).

Known gaps to fix or accept:

- Auth: expired-session cleanup, a cap on sessions, 503 instead of 500 on a database outage, the standard error body on 413, a cap on concurrent password hashing, a `__Host-` cookie name, refusing a localhost `ALLOWED_ORIGINS` in production, CAPTCHA on signup.
- No email service: no verification and no password reset.
- Account deletion does not exist. When it does, it must protect a workspace's last owner.
- A distributed attacker can hold one account at the 50-failure ceiling (accepted).
- Workspaces: nobody can be invited; rename, leave, role changes and removal have an API but no screen. Promoting a member who owns 20 workspaces reveals that fact; a member removed mid-request can receive the member list once.
- Frontend: the Slice 1.4 follow-ups below.

## Slice log

### Slice 0.1 — Repository audit
- **Date:** 2026-11-20
- **What changed:** Initialised Git (`main`), added `origin` remote, audited the repository, added `.gitignore`, `docs/REPOSITORY_AUDIT.md`, and this file.
- **Files/modules affected:** `.gitignore`, `PROJECT_STATUS.md`, `docs/REPOSITORY_AUDIT.md`
- **Tests run:** None applicable (no code exists). Baseline = no tests/build.
- **Test results:** N/A
- **Manual checks:** Confirmed repository root; confirmed only `AGENT_BUILD_GUIDE.md` existed and it is unchanged; confirmed remote is empty and public; confirmed Git identity resolves to the owner's global config; confirmed `git status` shows only intended files.
- **Known limitations / blockers:** Docker not installed locally (Compose unverifiable on this machine).
- **Commit:** `7d8238d`
- **Push result:** Success — created `origin/main`
- **Next smallest task:** Slice 0.2

### Slice 0.2 — MVP specification
- **Date:** 2026-11-20
- **What changed:** Product vision, master PRD with testable acceptance criteria (IDs AUTH/WS/AGT/MDL/CHAT/KB/MEM/TOOL/USE/DATA), explicit exclusions, open questions, roadmap, ADR-0001 recording provisional decisions. Added `.gitattributes` to normalise line endings (LF).
- **Files/modules affected:** `docs/PRODUCT_VISION.md`, `docs/MASTER_PRD.md`, `docs/ROADMAP.md`, `docs/decisions/ADR-0001-provisional-product-decisions.md`, `.gitattributes`
- **Tests run:** Documentation review only (no code).
- **Manual checks:** Every in-scope MVP feature has an acceptance criterion; every excluded feature is listed; the 10-step MVP journey depends on no excluded feature.
- **Known limitations / blockers:** None.
- **Commit / push:** `f8837d4` — pushed to `origin/main`
- **Next smallest task:** Slice 0.3 — architecture and stack decisions

### Slice 0.3 — Technical foundation
- **Date:** 2026-11-20
- **What changed:** System architecture document; ADR-0002 (stack), ADR-0003 (server-side session auth), ADR-0004 (PostgreSQL-backed jobs).
- **Files/modules affected:** `docs/SYSTEM_ARCHITECTURE.md`, `docs/decisions/ADR-0002..0004`
- **Tests run:** Documentation review only.
- **Manual checks:** One framework/ORM/migration tool/queue/test approach per layer; modular monolith preserved; no duplicate package managers chosen.
- **Known limitations / blockers:** None.
- **Commit / push:** `273ef75` — pushed to `origin/main`
- **Next smallest task:** Slice 0.4

### Slice 0.4 — Reproducible local development
- **Date:** 2026-11-20
- **What changed:** FastAPI backend skeleton (settings with `SecretStr` DB URL, lazy engine, request-ID middleware, standard error format, `/api/health` liveness and `/api/health/ready` readiness). Next.js 15 frontend shell with central brand config, typed API client, and a System status panel (loading / ready / degraded / offline + Retry). `/api/*` rewrite to the backend. `.env.example` files (placeholders only), optional `docker-compose.yml` (pgvector/pg17 with healthcheck), README setup/run/test/shutdown/troubleshooting.
- **Files/modules affected:** `backend/**`, `frontend/**`, `docker-compose.yml`, `README.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend unit/API tests | PASS (9) | `backend: .venv\Scripts\python -m pytest` | liveness, readiness ok/not_configured/unavailable, no secret in response/logs, error format, request IDs, 500 safety |
| Backend lint/format | PASS | `ruff check .` / `ruff format --check .` | |
| Frontend component tests | PASS (5) | `frontend: npm test` | ready, not configured, DB down, offline + retry, proxy 502 |
| Frontend lint / types | PASS | `npm run lint` / `npm run typecheck` | |
| Frontend build | PASS | `npm run build` | |
| Integration with real DB | BLOCKED | — | no local DB credentials |
| Docker Compose | BLOCKED | — | Docker not installed on dev machine |

- **Manual checks:** Ran `uvicorn` → `GET /api/health` 200, `/api/health/ready` 503 `not_configured`. Ran `next start` → same response through the `/api/*` proxy; browser shows "Service degraded: The database is not configured…" with a Retry button.
- **Known limitations / blockers:** DB readiness never verified as `ok` against a real database yet (blocked as above). `starlette.testclient` emits a deprecation warning about `httpx`; harmless for now. `eslint@9` is flagged deprecated by npm but is what `eslint-config-next@15` supports. First `npm install` hung on a registry fetch and was retried with `--fetch-timeout`; noted in README.
- **Commit / push:** `1b8b785` — pushed to `origin/main`
- **Next smallest task:** Slice 1.1 (blocked on DB credentials)

### Slice 1.1 — Database and migrations
- **Date:** 2026-11-21
- **What changed:** Request-scoped SQLAlchemy session (no implicit commit, rollback on error). Models plus the initial Alembic migration for `users`, `workspaces`, `memberships` and `sessions`:
  - UUID keys via `gen_random_uuid()`, `timestamptz` everywhere
  - Case-insensitive unique email (`lower(email)` index)
  - Hash-only session tokens with `expires_at`/`revoked_at`
  - `owner`/`member` role check constraint
  - Hard-delete `ON DELETE CASCADE`
  - Alembic reads `DATABASE_URL` from settings.

  The test suite creates and drops its own `agently_test`/`agently_migrations_scratch` databases behind a `_test`/`_scratch` name guard, and DB tests skip loudly when `DATABASE_URL` is unset. Added a development-only idempotent seed script and `docs/DATABASE_DESIGN.md` (deletion behaviour, PRD DATA-1).
- **Plan:** `docs/plans/2026-11-21-1341-feat-database-and-migrations-plan.md`
- **Files/modules affected:** `backend/app/core/{database,model_mixins}.py`, `backend/app/models.py`, `backend/app/modules/{identity,workspaces}/`, `backend/alembic.ini`, `backend/migrations/`, `backend/scripts/seed_dev.py`, `backend/tests/*`, `backend/pyproject.toml`, `README.md`, `docs/DATABASE_DESIGN.md`, `docs/SYSTEM_ARCHITECTURE.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (44, incl. 21 DB tests that ran) | `backend: .venv\Scripts\python -m pytest` | Fresh-DB upgrade, downgrade/re-upgrade, no model drift, email/membership/role/FK constraints, both cascades, session lifecycle, seed idempotency, drop guard, no password in migration errors |
| Backend tests without DB | PASS (23) + SKIPPED (21) | `DATABASE_URL= .venv/Scripts/python -m pytest` (Git Bash) | Printed `21 database tests SKIPPED: DATABASE_URL not set`; the skipped tests are not counted as passes |
| Test sensitivity | Verified | temporarily broke the migration | Removing the workspace cascade and the email index failed 3 tests; restored |
| Backend lint/format | PASS | `ruff check .` / `ruff format --check .` | |
| Migrations on dev DB | PASS | `alembic upgrade head`, `alembic check`, `downgrade base`, `upgrade head` | `No new upgrade operations detected` |
| Seed script | PASS | `python -m scripts.seed_dev` (x2) | Created demo user/workspace, then no-op |
| Readiness | PASS | `curl.exe http://localhost:8000/api/health/ready` | `{"status":"ready","checks":{"database":"ok"}}` |
| Frontend tests / lint / types | PASS (5) | `npm test`, `npm run lint`, `npm run typecheck` | Unchanged |

- **Manual checks:** After test runs, `agently_test` and `agently_migrations_scratch` no longer exist and the dev `agently` database is untouched. The other databases on the server (`urbanpulse`, `urbanpulse_test`) are never used: the suite only uses its two fixed names.
- **Code review:** Run inline in one context by the implementing agent across correctness, testing, migration, security and standards. No reviewer subagents and no cross-model peer, so the review was not independent. Two minor fixes applied: corrected the ownerless-workspace wording in `docs/DATABASE_DESIGN.md`, and the health tests now also clear the cached session factory.
- **Known limitations / blockers:**
  - The ownerless-workspace gap stays open for Slice 1.3 (see above).
  - Two pytest runs at the same time on one machine would share and force-drop `agently_test`.
  - Windows PowerShell 5.1 deletes a variable set to `""`, so check the no-DB path from Git Bash (`DATABASE_URL= ...`).
  - No CI workflow yet.
- **Commit / push:** `7a9f7bc` (code), `2383ca8` (docs) — both pushed to `origin/main`.
- **Independent review (after commit):** 7 Claude reviewer subagents, no external model; verdict "Ready with fixes", no P0/P1. Follow-up fix `92f0b86`: a `?dbname=` query parameter in `DATABASE_URL` could point test engines at the dev database. Learnings: `docs/solutions/` (`1ff8e1e`). The open P2/P3 items (concurrent-run name collisions, a fully skipped run exits 0, no host check) are listed in `docs/solutions/best-practices/guarded-self-managing-test-databases.md`.
- **Next smallest task:** Slice 1.2 — authentication

### Slice 1.2 — Authentication
- **Date:** 2026-11-23
- **What changed:** Register, login, logout and `GET /api/auth/me` with revocable cookie sessions (Argon2id passwords, hash-only tokens, 14-day absolute lifetime). Strict Origin check on every state-changing request. Login and signup throttling in PostgreSQL (bounded, hashed keys; per IP, per account-and-IP pair, and a higher per-account ceiling). Auth event log without secrets. Route inventory test that fails for any unprotected new route. Minimal `/register`, `/login` and `/account` pages. Seed script: random password, local databases only. `ROLES` is now the source of the role check constraint. SQL error logs no longer include parameters; request bodies are limited to 64 KB.
- **Plan:** `docs/plans/2026-11-21-1428-feat-authentication-plan.md`
- **Files/modules affected:** `backend/app/core/`, `backend/app/modules/identity/`, `backend/migrations/versions/0002_auth_throttle_events.py`, `backend/scripts/seed_dev.py`, `backend/tests/`, `frontend/src/features/auth/`, `frontend/src/app/{register,login,account}/`, `docs/manual-checks/auth-browser-check.js`, ADR-0003, `docs/SYSTEM_ARCHITECTURE.md`, `docs/DATABASE_DESIGN.md`, `README.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (187) | `backend: .venv\Scripts\python -m pytest` | |
| Backend tests without DB | PASS (97) + SKIPPED (90) | `DATABASE_URL= .venv/Scripts/python -m pytest` (Git Bash) | Skips are loud and not counted as passes |
| Backend lint/format | PASS | `ruff check .` / `ruff format --check .` | |
| Test sensitivity | PASS (10 of 10 caught) | temporarily broke one guard at a time | Origin, IP count reset, commit before count, cleanup, throttled-row removal, revocation, expiry, missing commits, unprotected `/me` |
| Migrations on dev DB | PASS | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head` | `check` does not compare check constraints; a unit test pins the role constraint text |
| Frontend | PASS (21) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | |
| Browser check through the real proxy | PASS (21) | see below | Exits 1 with the backend stopped, and with uvicorn's default proxy handling |
| Seed script on dev DB | PASS (no-op only) | `python -m scripts.seed_dev` | The demo user already existed; the create path is covered by tests |

- **Re-run the browser check** (repository root; backend with `--no-proxy-headers`, frontend running; `SIGNUP_LIMIT_PER_IP=100` and `LOGIN_LIMIT_PER_IP=200` in `backend/.env`):

  ```powershell
  node "$HOME\.claude\plugins\cache\playwright-skill\playwright-skill\5.0.0\skills\playwright-skill\run.js" docs/manual-checks/auth-browser-check.js
  ```

- **Public routes (audit 2.1):** `GET /api/health`, `GET /api/health/ready`, `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`; outside production also `GET /api/docs`, `GET /api/openapi.json`, `GET /docs/oauth2-redirect`. Private: `GET /api/auth/me`.
- **Audit notes:** 2.3 not applicable (no email service); 2.7 not applicable (no OAuth provider); 6.1 client-IP source **Suspected** until a hosting target is chosen.
- **Review:** plan reviewed by six Claude reviewers. Code reviewed twice: first by two independent Claude reviewers, then, after those fixes, by the eleven `ce-code-review` reviewers (no P0/P1; no other-model reviewer was available). The implementing agent merged those findings itself instead of using the separate merge, validator and report steps. The simplify pass was not run. Fixed from review: uvicorn rewrote the client IP from `X-Forwarded-For` (real throttle bypass, reproduced in the browser check), SQL errors logged hashes, a lone-surrogate password returned 500, unlimited request bodies, IPv6 rotation, throttled attempts briefly counting against the account, a delete-order deadlock, seed host bypasses, and weak tests.
- **Known limitations / follow-ups:**
  - Databases seeded before this slice still hold the demo user with the old published password. Delete that user and its Demo Workspace, then re-seed. Done for the local dev database on 2026-11-23.
  - `ENVIRONMENT` defaults to `development`, so a deployment that forgets it gets no production checks. Fixed 2026-11-24: it defaults to `production`.
  - With Next.js as the only proxy, all users share one IP bucket (20 failed logins per 15 minutes, 5 signups per hour for everyone). Production needs an edge proxy that appends to `X-Forwarded-For`.
  - An attacker with several IPs can still reach the per-account ceiling of 50 and block that account's login while the attack lasts (accepted).
  - Not done: expired-session cleanup and a cap on active sessions, 503 instead of 500 on database outage in auth routes, the standard error format on a 413 (oversized body), a cap on concurrent password hashing (64 MiB each, up to 40 threads), a `__Host-` cookie name in production, CAPTCHA on signup (6.3), refusing a localhost `ALLOWED_ORIGINS` in production.
  - Emails are limited to printable ASCII.
  - The browser check left throwaway users in the dev database. Fixed 2026-11-24.
- **Not green:** gstack `/verify` could not run the backend tests on this machine: it calls `python3`, which is the Windows Store alias (`Python was not found`, exit 49). Its frontend lane passed. The same backend suite passes when run directly (table above).
- **Commit / push:** `db4c4ae` (backend), `3070b54` (frontend and browser check) — pushed to `origin/main`; the docs commit follows.
- **Next smallest task:** Slice 1.3 — workspace and membership

### Slice 1.3 — Workspaces and membership
- **Date:** 2026-11-23
- **What changed:** Registration creates a personal workspace in the same transaction. Create, list, open, rename and delete workspaces; list members, change roles, remove members, leave. Non-members get 404, members without the owner role get 403. The last owner is protected by row locks, and a person owns at most 20 workspaces. Pages `/workspaces` and `/workspaces/<id>`. No schema change. People cannot be invited yet (owner decision).
- **Plan:** `docs/plans/2026-11-23-1215-feat-workspaces-and-membership-plan.md`
- **Files/modules affected:** `backend/app/modules/workspaces/`, `backend/app/modules/identity/service.py`, `backend/tests/test_{workspaces_api,tenant_isolation,workspace_concurrency}.py`, `frontend/src/features/workspaces/`, `frontend/src/app/workspaces/`, `docs/manual-checks/workspace-browser-check.js`
- **Phase 1 exit-gate proof — tenant isolation matrix:** `backend/tests/test_tenant_isolation.py`, generated from the registered routes:
  - `test_every_route_uses_the_membership_check_or_is_allowlisted`: any new route must use the check or be allowlisted on purpose, whatever its path.
  - `test_outsider_gets_404_and_no_data`: every verb of every workspace and member endpoint, as another signed-in user. 404, no data, nothing changed in any table except the throttle log.
  - `test_own_workspace_does_not_open_another_tenants_objects`: own workspace id with another tenant's object id.
  - Also: 404 before body validation, 401 when signed out, 405 for other verbs, and lists never show another tenant.
- **Race proof:** `backend/tests/test_workspace_concurrency.py`. Separate connections; each race waits until PostgreSQL reports the requests blocked.
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (292) | `backend: .venv\Scripts\python -m pytest` | Concurrency file repeated without a failure |
| Backend tests without DB | PASS (115) + SKIPPED (177) | `DATABASE_URL= .venv/Scripts/python -m pytest` (Git Bash) | |
| Lint, format, `alembic check` | PASS | `ruff check .`, `ruff format --check .`, `alembic check` | No migration needed |
| Test sensitivity | PASS | removed one guard or lock at a time | Both locks, re-check under lock, limit lock, refresh order, membership filters, unguarded route: all caught. Removing only the route-level owner check changes nothing, because the service re-checks under the lock |
| Frontend | PASS (38) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | |
| Browser checks through the real proxy | PASS (14 + 21) | commands in `README.md` | Workspace and auth journeys |

- **Review:** two Claude reviewers (tenant isolation and access control; data and concurrency). No P0/P1. Fixed: matrix recognised routes by path spelling, no foreign-object matrix, a rename could return 500 after succeeding, a narrow deadlock (the workspace row is now locked before the owner rows), a race test that could pass without the race, and invisible or misleading names. Then an owner-run ultrareview of the fixed code: two nits, both confirmed and fixed (a session ending, or the workspace disappearing, during create or delete; duplicated button and error markup). Those last fixes were tested but not re-reviewed.
- **Known limitations / follow-ups:**
  - Promoting a member who already owns 20 workspaces fails with `workspace_limit`, which tells the owner that fact. Unreachable until people can join a workspace.
  - Someone removed at the same moment as they request the member list can receive it one last time.
  - Accounts from before this slice have no workspace until they create one.
- **`/verify`:** runs on Windows now. `.gstack/pregate.json` points it at `scripts/run_tests.py`, which uses `backend/.venv` and runs each suite from its own folder. gstack reads that file from `origin/main`, so it applies once pushed. A test fails when a test file is missing from its mapping: add new test files there.
- **Commit / push:** `8d9e0fc` (backend), `bb657cd` (frontend and browser check), `4591457` (docs); review fixes and tooling follow. Pushed to `origin/main` together.
- **Next smallest task:** Slice 1.4 — dashboard shell

### Slice 1.4 — Dashboard shell
- **Date:** 2026-11-24
- **What changed:** One layout for all signed-in pages (sidebar on laptop, the same column behind a menu button below that) with a workspace switcher, Dashboard, Settings, Account and sign out. Sign-in and registration open the last-used workspace, or the first, or the create form. The dashboard shows the role and member count from the API and says agents are not available yet. Settings holds the existing member list and owner-only delete. The home page offers "Go to dashboard" when signed in. No backend or schema change.
- **Plan:** `docs/plans/2026-11-24-0927-feat-dashboard-shell-plan.md`
- **Last-used workspace:** browser storage, key contains the user id, value is the workspace id, nothing else. It survives sign-out, grants nothing, and blocked storage is tolerated (unit and browser tested).
- **Files/modules affected:** `frontend/src/features/{shell,workspaces,auth}/`, `frontend/src/app/`, `frontend/src/components/`, `frontend/src/lib/{lastWorkspace,usePageRouter}.ts`, `docs/manual-checks/`, `.gstack/pregate.json`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Frontend | PASS (73) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | |
| Test sensitivity | PASS (14 of 14 caught) | broke one guard at a time | Request order, remembered value, account change, session end, Back restore, focus, storage key, late navigation |
| Browser checks through the real proxy | PASS (90 + 21 + 14) | commands in `README.md` | Dashboard check: axe-core at 320, 375, 768 and 1280 px and in dark mode, keyboard, no horizontal scroll, server failure, blocked storage |
| Backend with real DB | PASS (292) | `.venv\Scripts\python -m pytest` | Unchanged; re-run for the exit gate |
| Backend lint, format, `alembic check` | PASS | | |

- **Review:** one focused Claude reviewer (frontend and accessibility). No P0/P1. All five P2 findings fixed: a late answer could navigate someone off the page they moved to; layout and page could show two accounts after a sign-in in another tab; a page restored by Back could show signed-in data; no loading state between workspaces; switching workspace was not announced. Also fixed: focus lost on Retry, modified clicks, the sidebar disagreeing with a not-found page, page titles, delete wording, upper-case ids, test gaps. The fixes were tested but not re-reviewed. axe found two more, both fixed: sidebar content outside a landmark, and error screens without a heading.
- **Known limitations / follow-ups:**
  - If only the layout's refresh fails after creating a workspace, the switcher shows "None selected" until the next navigation or return to the tab.
  - On the home page, focus is lost if the visitor has already tabbed to "Create account" when the session check answers.
  - Back-restore protection is unit tested; the browser check cannot exercise it because Playwright's Chromium disables that cache.
  - Returning to a tab refreshes the layout, not the page's own data, unless the account changed.
  - Signing in always opens the dashboard, not the page where a session ended.
  - No screen-reader software was run; keyboard checks of the menu run at phone width, of the switcher at laptop width.
- **Commit / push:** `feat(dashboard)` and `docs` commits of 2026-11-24, pushed to `origin/main` together.
- **Next smallest task:** Slice 2.1 — agent data model and APIs

### Follow-up — fail-safe ENVIRONMENT and browser-check cleanup
- **Date:** 2026-11-24
- **What changed:** `ENVIRONMENT` now defaults to `production` (owner decision). A blank value stops startup. `backend/.env.example` and the local `backend/.env` already set `development`; the test suite selects `development` itself when nothing is set. The browser checks delete the accounts they register, through `backend/scripts/delete_check_accounts.py` (only `browser-check-*@example.com`, only `ENVIRONMENT=development` with a local database). The 17 accounts left by earlier runs were deleted.
- **Tests run / results:** backend 310 pass; without `backend/.env` 130 pass and 180 database tests SKIPPED; `ruff` clean. Restoring the old default fails 5 tests. Browser checks 91 + 22 + 15 pass, and only the demo user remains afterwards. Seed script runs.
- **Known limitations:** one full run ended with a teardown error dropping `agently_test`; cause found and fixed below. A browser check killed midway leaves its accounts: `python -m scripts.delete_check_accounts --all`.
- **Next smallest task:** Slice 2.1 — agent data model and APIs (not started, waiting for the owner)

### Follow-up — reliable drop of the test databases
- **Date:** 2026-11-24
- **What changed:** `DROP DATABASE ... WITH (FORCE)` also tries to terminate other roles' processes, and a non-superuser may not terminate an autovacuum worker. The test helpers now end only client connections of the current role, then use a plain DROP (which stops autovacuum itself), up to 5 tries 0.5 s apart while the database is in use. The final error lists pid, backend_type, usename and application_name of each holder. No privileges granted. PostgreSQL hides backend_type of other roles' processes, so an autovacuum worker shows as `hidden` with usename `none`.
- **Proof:** reproduced on PostgreSQL 18.6 with a real autovacuum worker: FORCE fails with the same error as before, the new drop succeeds. `backend/tests/test_db_drop.py` covers the filter; removing any of its four conditions fails the test.
- **Tests run / results:** backend 316 pass, twice; without a database 133 pass and 183 SKIPPED; `ruff` clean.
- **Next smallest task:** Slice 2.1 — agent data model and APIs (not started, waiting for the owner)

### Slice 2.1 — Agent data model and APIs
- **Date:** 2026-11-24
- **What changed:** Agents and immutable configuration versions (migration `0003`). List, view, create, edit, duplicate, pause, resume, archive and restore for any member; permanent delete for owners only. Edits state the version they started from (409 when outdated); a save that changes nothing makes no version. Limits: 50 agents per workspace (archived included) and 60 create/edit/duplicate requests per user per 10 minutes, both configurable; 200 versions per agent. One rule decides whether an agent may run. The model reference exists but stays empty until 3.1.
- **Plan and ADR:** `docs/plans/2026-11-24-1020-feat-agent-data-model-and-apis-plan.md`, `docs/decisions/ADR-0005-agent-deletion.md`. The ADR changes the PRD (owner-only delete) and records the conversation/execution cascade for Slice 3.2 and that usage rows survive deletion of agents, executions and workspaces.
- **Isolation:** every agent route uses the membership check and joined the matrix automatically; until a real agent was supplied for the attacks, every route with an agent id failed the suite. New for all routes: the rightful owner must not get 404, someone in two workspaces cannot cross them, one path parameter is attacked at a time, and reads of your own workspace may not show another's data.
- **Files/modules affected:** `backend/app/modules/agents/`, `backend/app/core/{text,config}.py`, `backend/app/modules/{workspaces,identity}/`, `backend/migrations/versions/0003_agents.py`, `backend/tests/`, `.gstack/pregate.json`, `docs/`, `README.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (526) | `backend: .venv\Scripts\python -m pytest` | No skips |
| Backend tests without DB | PASS (133) + SKIPPED (379) | `DATABASE_URL= .venv/Scripts/python -m pytest` (Git Bash) | Run before the review fixes |
| Lint and format | PASS | `ruff check .`, `ruff format --check .` | |
| Migrations on dev DB | PASS | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head`, `check` | |
| Test sensitivity | 23 of 25 caught | broke one guard at a time | The two others, the early owner check on delete removed or reordered, are covered by a second layer, so nothing observable changes. 24 ran before the review fixes, the lock-release one after |

- **Review:** one focused Claude reviewer (security and concurrency), no external model. No P0/P1. Fixed: an unchanged edit kept its locks until the response was sent (P2); matrix loopholes for future collection and nested routes (P2); two test gaps (P3). Recorded: account deletion must lock workspaces first (`docs/DATABASE_DESIGN.md`).
- **Known limitations:**
  - AGT-3's chat error waits for Phase 3; only the run rule exists.
  - Bodies that are not JSON get 422 before any check and are not counted by the write limit. Requests refused with 404 are not counted either.
  - Agent writes take turns within a workspace. There was no lock timeout until Slice 2.2.
  - No screens, no version history or rollback, no model choice.
- **Commit / push:** `feat(agents)` commit of 2026-11-24, pushed to `origin/main`.
- **Next smallest task:** Slice 2.2 — My Agents interface

### Slice 2.2 — My Agents interface and write timeouts
- **Date:** 2026-11-24
- **What changed:** My Agents: list (current and archived), agent page with every action, one form for create and edit. Delete is offered to owners only and needs the typed name. Nothing changes on screen before the server confirms; an unclear outcome is said to be unclear. Conflicting edits keep the typed text and never overwrite. Live instructions counter with a client-side limit. Leaving with unsaved text asks first (close, reload, links, Back, sign out, ended session); no drafts. User text is plain text only (audit 5.2). The dashboard shows the real agent count. Agent and workspace writes give up after 5 s waiting for a lock, and the database ends one stalled for 30 s; both answer 503 `busy`.
- **Plan:** `docs/plans/2026-11-24-1112-feat-my-agents-interface-plan.md`
- **Files/modules affected:** `frontend/src/features/agents/`, `frontend/src/app/(app)/workspaces/[id]/agents/`, `frontend/src/lib/`, `frontend/src/features/{auth,shell,workspaces}/`, `backend/app/core/`, `backend/app/modules/workspaces/service.py`, tests, `docs/manual-checks/`, `.gstack/pregate.json`, docs
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (545) | `backend: .venv\Scripts\python -m pytest` | No skips |
| Backend tests without DB | PASS (133) + SKIPPED (412) | `DATABASE_URL= .venv/Scripts/python -m pytest` (Git Bash) | |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Frontend | PASS (123) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | |
| Browser checks, production build | PASS (116 + 99 + 22 + 15) | `docs/manual-checks/` | agents, dashboard, auth, workspace |
| Test sensitivity | 22 of 22 caught | broke one guard at a time | Two were missed at first; both tests were fixed |

- **Review:** one focused frontend and accessibility review by the implementing agent, so not independent. Fixed: links and buttons inside an alert region, focus lost on the count's Retry, unclear message when the agent is gone while saving.
- **Known limitations:**
  - The member view without delete is covered by component tests only: nobody can be invited yet.
  - A different account signing in from another tab discards typed text without asking, so one account never sees another's.
  - After a create, Back opens an empty create form.
  - The lock timeout applies to each lock. On Windows the server's reason for closing a connection is lost, so any connection lost during a limited write, except at COMMIT, is reported as `busy`.
  - Next.js can leave an unused second title element in the page; the tab title is correct.
  - One browser-check run timed out waiting for Restore; not reproduced in 80 targeted repeats or the later full runs, cause unknown.
- **Commit / push:** `feat(agents)` commit of 2026-11-24, pushed to `origin/main`.
- **Next smallest task:** Slice 2.3 — Prompt-to-Agent builder

### Slice 2.3 — Prompt-to-Agent builder
- **Date:** 2026-11-24
- **What changed:** Members answer five questions and get a draft in the agent form, which they edit and save themselves. Generating saves nothing. Output must be one JSON object of exactly name, purpose, description and instructions, without duplicate keys or hidden characters; anything else is rejected whole, without retries. Answers are escaped inside `<user_answer>` tags; a snapshot test holds the exact prompt. Limits: 10 generations per user and 30 per workspace per hour, 1,000 characters per answer, 3,000 together, 8 calls at once per process. New provider interface (system, user and assistant messages, timeout, output token limit; text and token counts) with a mock only. Without a provider the option is hidden; production refuses the mock.
- **Also:** only one backend test run at a time can use the test databases (PostgreSQL advisory lock); a second one stops at once with a clear message.
- **Plan:** `docs/plans/2026-11-24-1228-feat-prompt-to-agent-builder-plan.md`
- **Files/modules affected:** `backend/app/modules/{providers,agent_builder}/`, `backend/app/modules/{agents,identity}/`, `backend/app/core/config.py`, `backend/tests/`, `frontend/src/features/agents/`, `frontend/src/lib/unsavedChanges.ts`, `docs/`, `.gstack/pregate.json`, `README.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (883) | `backend: .venv\Scripts\python -m pytest` | No skips, run alone |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Frontend | PASS (150) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | |
| Browser checks, production build | PASS (42 + 116 + 99 + 22 + 15) | `docs/manual-checks/` | builder, agents, dashboard, auth, workspace; mock set for the test server only |
| Test sensitivity | 41 of 42 caught | broke one guard at a time | The other was redundant code, removed |
| Real provider | BLOCKED | | No key. The prompt-to-agent part of the Phase 2 exit gate is proven with the mock only |

- **Review:** one independent Claude security reviewer on the backend, no external model. No P0/P1. Fixed: single joiners could carry hidden text between visible letters; slow calls could occupy every worker thread; a cleanup test that proved nothing; adapter errors and wrong return values could leak text or cause a 500; duplicate keys; rare invisible characters; invisible characters in source. Changes after the review, including the test lock, were not reviewed independently. The frontend was self-reviewed.
- **Known limitations:**
  - The flags of England, Scotland and Wales make a draft invalid (owner decision: recorded, not fixed). So do right-to-left marks, Thai zero-width spaces, soft hyphens, CJK and Mongolian variation selectors, and emoji newer than Python's Unicode tables.
  - Joiners inside Arabic and Indic words, emoji styles and no-break or thin spaces stay allowed and could still carry a little hidden data. Many stacked accents can obscure text. Instructions typed by hand are not checked for hidden characters.
  - Hidden characters in an answer are not refused up front: if the draft repeats them, the generation is used up and the message speaks of the AI's draft.
  - Schema checks cannot judge what instructions say. The mock follows no instructions, so a real model's resistance to injection is untested.
  - A validation error names an unknown field the caller sent, as everywhere in the API.
  - A crash between recording the two limits counts one attempt without a call; simultaneous requests at a limit can refuse each other, but never exceed it.
  - Untested: that the user limit is checked before the workspace limit (either order gives the same result today), and parallel generations against the limits (the shared throttle has such a test). The source-text check that generation cannot write agents is weak; the checks that no agent exists are the real guard.
  - `backend/.env` was left unchanged: add `MODEL_PROVIDER=mock` there to use the builder locally.
- **Commit / push:** `feat(agents)` commit of 2026-11-24, pushed to `origin/main`.
- **Next smallest task:** Slice 2.4 — Agent configuration and versions (not started, waiting for the owner)

### Local fix — dev server port
- **Date:** 2026-11-24
- **What changed:** `npm run dev` uses port 3000 or stops. A leftover `next start` from the Slice 2.3 checks held 3000, so Next.js moved to 3001; pages loaded, because cookies ignore ports, but every write came from `http://localhost:3001` and was refused. The Origin check is unchanged.
- **Checked:** Edge, headless: 403 on 3001 and a draft on 3000; then a draft on the restarted dev server on 3000. `/verify` green.
- **Commit / push:** `063ee62`, pushed to `origin/main`.

### Slice 2.4 — Agent configuration and versions
- **Date:** 2026-11-24, finished 2026-11-25
- **What changed:** Version history (20 per page, with the names of the changed fields), a read-only view of each version, and rollback. Rollback saves a copy as a new version and records its source (migration `0004`); no version is ever changed. It follows the rules of editing: 409 when stale, 200 versions, not while archived, write limit, nothing saved when nothing changes; a version that breaks today's rules is refused. Savers are shown by email only while they are members, otherwise "Former member". Versions have unique ids in URLs. The limit message now names duplicating as the way on.
- **Isolation:** version routes joined the matrix automatically. New for every route naming an object inside another: both ids are attacked with a sibling agent of the same workspace, in both directions, with a positive control and a planted unguarded route.
- **Plan:** `docs/plans/2026-11-24-1521-feat-agent-versions-plan.md`. Assumptions made while the owner was away are listed there.
- **Files/modules affected:** `backend/app/modules/agents/`, `backend/migrations/versions/0004_agent_version_source.py`, `backend/tests/`, `frontend/src/features/agents/`, `frontend/src/lib/focusContent.ts`, `frontend/src/app/(app)/workspaces/[id]/agents/[agentId]/versions/`, `docs/`, `.gstack/pregate.json`, `README.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (995) | `backend: .venv\Scripts\python -m pytest` | No skips, final code |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Migration on dev DB | PASS | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head`, `check` | |
| Frontend | PASS (181) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | |
| Browser checks, production build | PASS (59 + 116 + 42 + 99 + 22 + 15) | `docs/manual-checks/` | versions, agents, builder, dashboard, auth, workspace. The test backend started before the last review fix to the rollback rule check, which only backend tests cover |
| Test sensitivity | 44 of 46 caught | broke one guard at a time | Backend 33 of 35, frontend 11 of 11. Survivors: the agent row lock (the workspace lock already makes writes take turns) and the query limit of a page (the result is cut to 20 anyway). One survivor was a missing test, added. The run was interrupted by low memory and finished later |
| Backend tests without DB | NOT RUN | | |

- **Also fixed:** `test_production_starts_when_configured` read the developer's `backend/.env` and failed once it named the mock. The test now sets the value; the guard is unchanged.
- **Review:** one independent Claude reviewer (security and concurrency), by reading only, no external model. No P0/P1. Fixed: a busy rollback did not offer the latest state (P2); the matrix had no planted unguarded route; its control accepted only 200; rollback could restore text that today's rules would clean up (P3s). Changes after the review were not reviewed again.
- **Known limitations:**
  - P3, recorded: the matrix attacks ids in paths only. A version id in a query string or body would need its own test; no route has one.
  - P3, recorded: if an agent is edited, archived and restored by others while a rollback is refused, the page moves to the newer version number without asking for a reload. It shows the number.
  - Reading a page of history loads the instructions of up to 21 versions on the server; they are not sent.
  - The rollback screen for members is covered by component and API tests only: nobody can be invited yet.
  - Guide 2.4 "execution metadata can identify the version" is BLOCKED until executions exist (Phase 3). Versions have permanent ids and numbers for it.
  - No side-by-side diff, labels or deletion of versions.
- **Commit / push:** `feat(agents)` commit of 2026-11-25, pushed to `origin/main`.
- **Next smallest task:** Phase 2 exit report, then Slice 3.1 (waiting for the owner)
