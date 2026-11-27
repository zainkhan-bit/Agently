# Project Status — Agently

**Current milestone:** Phase 4: Slice 4.1 is done; Slice 4.2 is built but not yet verified (local branch); Slice 4.3 is blocked
**Next smallest task:** verify Slice 4.2 (`/verify`, guard check) and merge it; Slice 4.3 is BLOCKED on pgvector (see below)

## Must fix before any deployment

- Run uvicorn with `--no-proxy-headers`, and put an edge proxy that appends to `X-Forwarded-For` in front (see Slice 1.2).
- Gemini (ADR-0006): the paid tier (production refuses free), a monthly spend cap set in AI Studio first, nobody under 18, and no users in the EEA, UK or Switzerland on the free tier.

- PostgreSQL's own log may record rows that a constraint refuses, message text included. Set `log_error_verbosity = terse` on the production server (review of Slice 3.2).

## Must do before Slice 3.4 ships

- DONE on `slice-3.4`: deleting an agent or a workspace warns that everyone's private conversations go too.
- STILL OPEN: removing a member has no screen yet (API only). The slice that adds that screen must warn that the member's conversations are deleted.

## Before enabling a real provider key

Agreed with the owner on 2026-11-24. Built in Slice 3.1:

- DONE: the describe page says who receives the answers, before anyone types.
- DONE: a hard deadline the adapter cannot exceed.
- DONE: a server-wide spending limit ($1 per 24 hours, $10 per 30 days).
- DONE: HTTP libraries do not log, also at `LOG_LEVEL=DEBUG`.
- NOT NEEDED on the free tier, which has no bill: a spending cap on the provider account. Required before the paid tier.
- DONE: the real-provider test (`backend/scripts/gemini_check.py`), a valid draft and a stream.

## Blocked / needs owner input

- ~~Slice 1.1 blocked on local PostgreSQL credentials~~ — resolved 2026-11-21: `GET /api/health/ready` returns `database: ok`.
- **Known gap (owner: the slice that adds account deletion):** it must refuse to delete a workspace's last owner, or transfer or delete the workspace first, with tests. Slice 1.3 enforces this for leaving, removal and demotion; account deletion does not exist in the app yet. Lock order and edge cases: `docs/DATABASE_DESIGN.md`.
- The real-provider tests of Slices 2.3 and 3.1 passed on 2026-11-25.
- ~~Slice 3.3, BLOCKED: the runtime check with the real provider~~: done on 2026-11-27 with the owner's pre-approval (at most 6 calls; 4 used). See the Phase 3 exit gate.
- ~~Slice 3.2, BLOCKED: breaking one guard at a time~~: rerun on 2026-11-27 with the owner's yes, one test file per process. See the Slice 3.4 review fixes.

- **Slice 4.3, BLOCKED (owner, needs admin rights):** the pgvector extension is not available on the local PostgreSQL 18.6: `SELECT * FROM pg_available_extensions WHERE name='vector'` returned no row (2026-11-27). Installing it needs administrator rights and the Visual Studio C++ build tools, so nothing was attempted. Steps (pgvector's own Windows instructions):
  1. Install "Desktop development with C++" from the Visual Studio Build Tools, if it is not there.
  2. Open "x64 Native Tools Command Prompt for VS" **as Administrator** and run:
     ```
     set "PGROOT=C:\Program Files\PostgreSQL\18"
     cd %TEMP%
     git clone --branch v0.8.1 https://github.com/pgvector/pgvector.git
     cd pgvector
     nmake /F Makefile.win
     nmake /F Makefile.win install
     ```
     Use the newest release tag on github.com/pgvector/pgvector if it is newer than v0.8.1, and adjust `PGROOT` if PostgreSQL is installed elsewhere.
  3. As the `postgres` superuser, enable it where the app and its tests need it: `psql -U postgres -d agently -c "CREATE EXTENSION IF NOT EXISTS vector;"` and `psql -U postgres -d template1 -c "CREATE EXTENSION IF NOT EXISTS vector;"` (the test databases are created from `template1`).
  4. Check: `SELECT * FROM pg_available_extensions WHERE name='vector'` returns one row. Then Slice 4.3 can start, with a mock embedding provider.
- **Slice 4.2, needs a run when memory allows:** the guard check was stopped, and the full suite and `/verify` were not started, because the machine ran critically low on memory (2026-11-27). The slice is committed on local branch `slice-4.2`.

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

## Phase 2 exit gate

Checked 2026-11-25, after Slice 2.4. **Both ROADMAP gates pass locally, but drafts were proven with the mock provider only until Slice 3.1.** There is no CI yet, so nothing re-runs these automatically. The numbers are browser checks.

| Gate (`docs/ROADMAP.md`) | Result | Proof |
|---|---|---|
| Agents created, edited, paused | PASS | `backend/tests/test_agents_api.py`: `test_members_and_owners_can_manage_agents`, `test_only_the_allowed_status_changes_happen`, `test_outdated_edits_are_refused_even_with_identical_text`; `test_agent_concurrency.py`; `frontend/src/features/agents/agents.test.tsx`; `docs/manual-checks/agents-browser-check.js` (116) |
| Drafts schema-validated | PASS; one real Gemini draft on 2026-11-25 | `backend/tests/test_agent_builder.py`: `test_a_draft_has_exactly_the_four_text_fields`, `test_bad_output_is_rejected_whole`, `test_output_cannot_set_other_fields`, `test_text_a_reviewer_cannot_see_is_rejected`; `frontend/src/features/agents/describe.test.tsx`; `docs/manual-checks/builder-browser-check.js` (42) |

The build guide words the gate further (Slice 2.4):

| Gate (`AGENT_BUILD_GUIDE.md`) | Result | Proof |
|---|---|---|
| Create by prompt | PASS; one real Gemini draft on 2026-11-25 | `test_members_generate_a_sample_draft_and_nothing_is_saved`; `builder-browser-check.js` |
| Create manually, edit, pause | PASS | as above |
| See it in your own workspace only | PASS | `backend/tests/test_tenant_isolation.py`, including `test_one_object_does_not_open_what_belongs_to_its_sibling`; isolation parts of `agents-browser-check.js` and `versions-browser-check.js` (59) |
| Generated configuration grants no permissions | PASS for what the server accepts, whatever a model returns | `test_output_cannot_set_other_fields`, `test_generation_has_no_way_to_write_agents` (weak, see Slice 2.3) |
| Versioned configuration (AGT-4) | PASS, except recording the version on an execution: BLOCKED until Phase 3 | `backend/tests/test_agent_versions.py`, `test_agent_concurrency.py`; `frontend/src/features/agents/versions.test.tsx` |

**Proven on the mock only**

- That a useful, valid draft comes back at all. The mock builds it from the answers.
- Timeouts, rate limits and outages: simulated failures, never a real network or provider.
- Token counts: made up by the mock.
- Injection: hostile *output* is rejected by the server and hostile *input* stays inside its wrapper, but whether a real model obeys hostile input is untested.

**Still open**

- AGT-3 "paused agents cannot run": the rule and its test exist (`test_only_active_agents_may_run`), but nothing runs agents until Phase 3.
- The member view of agents and versions is checked by API and component tests, not in a browser: nobody can be invited yet.
- Everything under "Before enabling a real provider key" and "Must fix before any deployment".

## Phase 3 exit gate

Checked 2026-11-27, after Slice 3.4 and its review fixes. **The gate passes locally, with one real Gemini conversation (4 calls).** There is no CI yet, so nothing re-runs these automatically. The numbers in brackets are browser checks.

| Gate (`AGENT_BUILD_GUIDE.md`) | Result | Proof |
|---|---|---|
| Chat with your own configured agent | PASS | `backend/tests/test_runtime.py`: `test_the_provider_gets_the_agents_prompt_the_history_and_the_limits`, `test_an_edit_during_the_call_does_not_change_the_recorded_version`; `frontend/src/features/chat/chat.test.tsx`; `docs/manual-checks/chat-browser-check.js` (48) |
| Real model responses | PASS on 2026-11-27 | `backend/scripts/chat_check.py` against a temporary server with `MODEL_PROVIDER=gemini` for that process only: two turns (the second remembered the first), a stopped answer (not stored, reported as stopped), its retry (stored once), a repeat without a call. 16 of 16 checks, 4 calls, $0.000679 at the configured prices (free tier: nothing billed). Server log: one warning (`answer not stored (stopped)`), no key, no message text |
| Revisit conversation history | PASS | `backend/tests/test_conversations.py`: `test_history_is_paged_backwards_and_each_page_is_in_order`, `test_the_list_is_paged_with_the_newest_activity_first`; refresh and reload parts of `chat-browser-check.js` |
| Only your own conversations | PASS | `backend/tests/test_tenant_isolation.py` (every conversation route, owners and members of the same workspace included); `test_conversations.py`: `test_storing_needs_the_creator_the_agent_and_the_membership`; privacy part of `chat-browser-check.js` |
| Provider credentials protected | PASS | `backend/tests/test_gemini.py`: `test_the_key_is_only_in_its_header`, `test_the_environment_cannot_redirect_the_key`; the key is only in `backend/.env` (ignored by git) and was never printed |
| Runtime limits exist | PASS | `test_runtime.py`: `test_user_and_workspace_limits`, `test_default_limits`, `test_parallel_calls_are_capped_and_slots_come_back`, `test_repeated_stop_and_retry_never_hold_more_than_one_slot_per_conversation`; `test_spending.py` (server-wide spending limit); `test_gemini.py`: `test_the_deadline_is_hard`, `test_the_number_of_workers_is_limited` |
| Paused agents cannot run (AGT-3, open since Phase 2) | PASS | `test_runtime.py`: `test_stopped_agents_do_not_run`; paused part of `chat-browser-check.js` |
| Version recorded on each answer (AGT-4, open since Phase 2) | PASS | `executions.agent_version` and `messages.agent_version`; `test_an_edit_during_the_call_does_not_change_the_recorded_version` |

**Proven on the mock only**

- Timeouts, rate limits, refusals and outages in chat: simulated, never a real provider failure.
- How a real model resists prompt injection: untested (agents have no tools, so a misled answer can only be misleading text).
- Long answers and the 4,000-token output limit with a real model.

**Still open**

- Markdown is not rendered: answers are plain text (a recorded Slice 3.4 decision).
- Everything under "Must fix before any deployment". The free tier stays local only (ADR-0006).
- No screen for removing members, so no warning there yet (see "Must do before Slice 3.4 ships").

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
- **Next smallest task:** Slice 3.1 (waiting for the owner)

### Slice 3.1 — Provider contract and Gemini adapter
- **Date:** 2026-11-25
- **What changed:** A Gemini adapter chosen with `MODEL_PROVIDER=gemini`, streaming on the provider interface and the mock, a tool-call type that nothing uses, an allowed-model list, a server-wide spending limit (migration `0005`), a hard deadline, silent HTTP libraries, and a notice of who receives the answers that the server enforces. Agents' `model` field stays empty. Tests cannot use a real key or the network.
- **Plan:** `docs/plans/2026-11-25-1240-feat-gemini-provider-plan.md`. Decision: ADR-0006 (Gemini instead of Anthropic).
- **Files/modules affected:** `backend/app/modules/{providers,agent_builder}/`, `backend/app/core/{config,logs}.py`, `backend/migrations/versions/0005_provider_spend.py`, `backend/scripts/gemini_check.py`, `backend/tests/`, `frontend/src/features/agents/`, `docs/`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (1164) | `backend: .venv\Scripts\python -m pytest` | No skips |
| Backend lint/format, migration on dev DB | PASS | `ruff check .`, `ruff format --check .`, `alembic upgrade head`, `check` | |
| Frontend | PASS (194) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | |
| Browser check, production build, mock | PASS (54) | `docs/manual-checks/builder-browser-check.js` | Other browser checks not re-run |
| Test sensitivity, backend | 70 of 70 caught | broke one guard at a time | 67 at first; the three survivors were missing tests, added. 15 of them cover the review fixes and refusal logging. Frontend guards not mutated |
| Real provider | PASS (draft and stream) | `python -m scripts.gemini_check --send` | 2026-11-25, three calls, `gemini-3.5-flash-lite`, free tier. Draft: valid, no fence, 409 tokens in, 131 out, 2.6 s. The first stream prompt (counting to thirty) got `provider_refused`, cause not recorded; refusal reasons from a fixed list are now logged, and with a new prompt the stream passed: 6 pieces, 29 in, 102 out, 1.6 s |

- **Review:** owner-run ultrareview of `a715c17`: one normal finding, two nits. Fixed: answers were lost when drafts were switched off while the form was open; the Gemini provider was rebuilt on every request. Also fixed, by the owner's decision of 2026-11-26: calls never sent, or refused with 401 to 404 or 429, give their reservation back (the review showed that they could block drafts for a day). That those statuses are free is our inference. The fixes were not reviewed again.
- **Known limitations:** the spending limit rests on Google's token counts and our price list; the tier is declared, not detected; `provider_spend` is never cleaned up; opening a database connection for a reservation is not covered by the provider deadline.
- **Commit / push:** branch `slice-3.1` merged into `main` and pushed on 2026-11-26. The local `.env` is switched to Gemini after the push.
- **Next smallest task:** Slice 3.2 — Conversation and message storage (not started, waiting for the owner)

### Slice 3.2 — Conversation and message storage
- **Date:** 2026-11-26 (owner away)
- **What changed:** Private conversations between one person and one agent: create, list, read in pages, delete (migration `0006`). Only the creator can reach one; owners and teammates get the 404 of a missing id. Every assistant message names a version of the same agent, enforced by the database. Storing messages is internal; no route accepts any. Deleted with the agent, workspace, account, or when the person leaves or is removed. Numbers: 8,000 and 32,000 characters, 500 messages, 200 conversations per person and agent, 30 created per hour.
- **Log safety:** `hide_parameters` was already on, but PostgreSQL's error details repeat whole rows. The engine now keeps only the primary message, also for the server's own traceback logging. SQLAlchemy and psycopg stay at WARNING at every `LOG_LEVEL`, because SQLAlchemy logs result rows at DEBUG.
- **Isolation:** all five routes joined the matrix by themselves. New: an owner and a member of the same workspace attack every route that names something private, with positive controls; a planted unguarded route is caught; a conversation may be named in paths only.
- **Plan:** `docs/plans/2026-11-26-0215-feat-conversation-storage-plan.md`, with the assumptions made while the owner was away.
- **Files/modules affected:** `backend/app/modules/conversations/`, `backend/app/core/{config,database,logs}.py`, `backend/app/modules/{agents,identity}/`, `backend/migrations/versions/0006_conversations.py`, `backend/tests/`, `.gstack/pregate.json`, docs
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (1336) | `backend: .venv\Scripts\python -m pytest` | No skips |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Migration on dev DB | PASS | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head`, `check` | |
| Test sensitivity | NOT RUN | 36 guards prepared | Stopped by the system for low memory before the first result; not restarted. It left one guard removed in the working tree, which was restored before the final test run and the commit |
| Frontend | unchanged | | |

- **Review:** one independent Claude reviewer (privacy and isolation), by reading only. No P0, P1 or P2. Five P3s; four fixed: weak concurrency tests, a DEBUG test that proved nothing, a matrix rule that knew only one parameter name, and missing `Cache-Control: private, no-store`. The fixes were not reviewed again.
- **Known limitations:**
  - P3, recorded: PostgreSQL's own server log (see "Must fix before any deployment"). Not reachable through `store_message` today.
  - Collections have no id to attack: the conversation list has its own test, a future aggregate would need one.
  - The list shows dates and counts only; titles are deferred.
- **Commit / push:** `feat(conversations)` commit of 2026-11-26, pushed to `origin/main`.
- **Next smallest task:** Slice 3.3 — Runtime service without tools

### Slice 3.3 — Runtime service without tools
- **Date:** 2026-11-26 (owner away)
- **What changed:** `POST .../conversations/<id>/messages` stores the person's message, asks the model with the agent's current version and recent answered history, and stores the answer with that version. The agent's configuration is in the system message only; user messages are escaped inside tags. Repeating a request never duplicates a message or call. Every attempt has an `executions` record without text (migration `0007`). Closing a run cancels it. One answer at a time per conversation; 60 messages per person and 200 per workspace and hour.
- **How it works:** `docs/AI_RUNTIME.md`. **Plan:** `docs/plans/2026-11-26-0240-feat-agent-runtime-plan.md`, with decisions and assumptions made while the owner was away.
- **Files/modules affected:** `backend/app/modules/runtime/`, `backend/app/modules/{conversations,providers,agent_builder,identity}/`, `backend/app/core/config.py`, `backend/migrations/versions/0007_executions.py`, `backend/tests/`, `.gstack/pregate.json`, docs
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (1456) | `backend: .venv\Scripts\python -m pytest` | No skips |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Migration on dev DB | PASS | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head`, `check` | |
| Test sensitivity | 37 of 43 caught | broke one guard at a time, in a copy outside the repository | One of them only after a weak cross-conversation test was fixed. The six survivors are redundant: the conversation key cascades too, joins already need an answer, Python closes an abandoned stream, store_message checks the text again |
| Real provider | BLOCKED | | Mock only |

- **Review:** one independent Claude reviewer (privacy, isolation, concurrency, money), by reading only. No P0 or P1. Fixed: unanswered messages used up the history window (P2); repeats of answered messages were refused by checks for new calls, text typed under one data notice was sent under another, a busy database claimed that nothing had changed, weak race tests (P3s). The fixes were not reviewed again.
- **Known limitations:**
  - P3, recorded: a crashed run's record says `running` until the next accepted message.
  - P3, recorded: one person can hold all 8 answer slots of a process for a while.
  - P3, recorded: lock waits plus the call can exceed the 30 seconds of the Next.js proxy. Repeating with the same id is safe.
  - How a real model resists prompt injection is untested. Agents have no tools.
  - The agent's instructions and a person's messages go to Google when Gemini is on.
- **Commit / push:** `feat(runtime)` commit of 2026-11-26, pushed to `origin/main`.
- **Next smallest task:** Slice 3.4

### Slice 3.4 — Chat interface and streaming
- **Date:** 2026-11-26 (owner away)
- **What changed:** A conversation list per agent and a chat page. Answers stream in as they are made (`POST .../messages/stream`, server-sent events), and a Stop button cancels them (`POST .../messages/stop`). Sending, answering, complete, stopped and failed are announced; failed and stopped messages can be retried with the same request, also after a reload. Loading, empty, error, not found, paused, archived and no-provider states. All text is plain text: no Markdown, no HTML. The data notice now also names the conversation so far and the agent's instructions. Owners are warned that deleting an agent or workspace deletes everyone's private conversations.
- **Found by the browser check:** the Next.js proxy keeps the backend connection open for 25 to 40 seconds after the browser stops reading, so a stopped answer kept running and blocked a retry. Fixed with the explicit stop route, which a running answer checks about once a second. A fix that only closed the stream better was tried, proved nothing, and was removed.
- **Also fixed:** Slice 3.3 changed the wording of `disclosure_changed`, which broke `builder-browser-check.js`. Now "Nothing was sent." **`main` (96ef4de) still has the old wording and fails that browser check until this branch is merged.**
- **Plan:** none written. The owner's Step 3 brief was the plan, with recommended options: separate list and chat pages, Enter sends and Shift+Enter starts a new line, plain text instead of Markdown (no renderer added), and the builder's notice reused for chat.
- **Files/modules affected:** `frontend/src/features/chat/`, `frontend/src/app/(app)/workspaces/[id]/agents/[agentId]/conversations/`, `frontend/src/features/{agents,workspaces}/`, `backend/app/modules/{runtime,providers}/`, `backend/app/core/config.py`, `backend/tests/`, `docs/manual-checks/`, `docs/AI_RUNTIME.md`, `.gstack/pregate.json`, `README.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (1504) | `backend: .venv\Scripts\python -m pytest` | No skips |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Frontend | PASS (220) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | 26 new chat tests, XSS included |
| Browser checks, production build, mock (`slow`) | PASS (46 + 116 + 54 + 99 + 22 + 15 + 59) | `docs/manual-checks/` | chat (new), agents, builder, dashboard, auth, workspace, versions. Axe and no horizontal scroll at 320, 375, 768 and 1280 px, and dark |
| Test sensitivity | 7 of 8, then 8 of 8 | broke guards one at a time, in a copy | Stopping one conversation stopped every running answer without a failing test: a test was added |
| Real provider | BLOCKED | | Mock only |

- **`/verify`:** NOT_READY, `tests=TIMEOUT`: its backend lane passed (1504 in 586 s), then the frontend lane ran out of time. Not a failure, not worked around; the frontend suite passes on its own (220).
- **Review:** self-review only (the owner runs `/code-review ultra`). Recorded: Stop pressed before the server has stored the message stops nothing, and behind the proxy the answer may then still be stored while the page says "Stopped".
- **Known limitations:** no Markdown; long conversations show 50 messages first with "Show earlier messages"; the list shows the newest 100 conversations; conversations have no titles; there is no screen for removing members.
- **Commit:** merged into `main` with the review fixes below.

### Slice 3.4 — Fixes from the owner's cloud review (`/code-review ultra`)
- **Date:** 2026-11-27
- **Findings:** 10 (4 normal, 6 nits), all fixed, each with tests.
- **What changed:**
  1. A stream whose connection closed before its first event never closed its run: the slot (8 per process) was lost and the record stayed `running`. The response now closes its events however it ends, also when the body was never read.
  2. Stop targets one message: `POST .../messages/stop` takes `{"request_id"}`. It only records a request (`executions.stop_requested_at`, migration `0008`); the run cancels its model call, waits for it to end, gives the slot back, and only then records `cancelled`/`stopped`. So one conversation never holds two slots, and the conversation stays busy until the call has really ended. The model call runs on its own thread, so a stop is noticed within about a second also while the model sends nothing. Providers take a `cancel` event (contract, spending wrapper, mock, Gemini). Stop waits up to 5 seconds for the end, so Retry right after works.
  3. The page: after a stop or failure, pending is cleared, so a new message can be sent at once. It reloads the newest messages and says what the server kept: the answer ("saved after all"), the message without an answer (Retry), or nothing (the text goes back into the box). Retry is offered only for a message the server has, and is always treated as possibly stored. Retry stays hidden until the server has handled the stop.
  4. A stopped answer is reported as "stopped", not "took too long", also when it was complete before the next check.
  5. A test that never covered a provider error in the middle of a stream now does (`provider_timeout`).
  6. The `slow` mock keeps to the timeout of the whole stream, and stops when cancelled.
  7. A stopped run records its end once (one transaction, one warning); a run given up by others records nothing more.
- **Files/modules affected:** `backend/app/modules/{runtime,providers}/`, `backend/migrations/versions/0008_execution_stop_requests.py`, `backend/tests/test_{runtime,gemini,spending,tenant_isolation,conversations}.py`, `frontend/src/features/chat/`, `docs/AI_RUNTIME.md`, `docs/manual-checks/chat-browser-check.js`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (1522, in 6 chunks of at most 6 files) | `backend: .venv\Scripts\python -m pytest` | No skips |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Migration on dev DB | PASS | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head`, `check` | `0008` |
| Frontend | PASS (225) | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | 5 new chat tests |
| Browser checks, production build, mock (`slow`) | PASS (48 + 116 + 54 + 99 + 22 + 15 + 59) | `docs/manual-checks/` | chat (2 new checks: Retry at once after a stop, a new message right after a stop), agents, builder, dashboard, auth, workspace, versions. Auth needs uvicorn's `--no-proxy-headers` |
| Test sensitivity, this fix | backend 17 of 18, frontend 8 of 9 | broke guards one at a time, backend in a copy | Backend: freeing the slot before settling was missed, a test was strengthened and now catches it; Gemini's worker check of the caller's cancel was redundant and was removed. Frontend: the survivor adds a `pending` check that is redundant once pending is cleared |
| Test sensitivity, Slice 3.2 (rerun) | 32 of 36 | one guard at a time, one test file per process, in a copy | First 31: a database check against a negative message count had no test; added. Survivors: the workspace clause of the creator filter and the delete's own 404 are redundant (the agent is the workspace's; the route's dependency 404s first); `updated_at` is also set by the ORM; the stale-count guard (`populate_existing`) needs a two-connection race test, not written |
| Real provider | PASS, after the merge | `backend/scripts/chat_check.py` | See the Phase 3 exit gate: 4 calls |

- **`/verify`:** `READY_FOR_SHIP tree=d4de833b862d checks=tests not_covered=none` (829 s, `--timeout 2400`). For this, `scripts/run_tests.py` now runs backend files 6 at a time, one pytest process after another (the whole suite in one process needs more memory than is free); a test covers it. The default 600 s limit is too short for the batched suite.
- **Known limitations:**
  - A stop that reaches the server before it has stored the message stops nothing; the page then shows what was kept, and the answer may arrive later (a retry is refused with `answer_in_progress` until then).
  - A Gemini worker waiting for the network may outlive a cancelled call until the connection gives something or its timeout; the call's runtime slot is free at once, its Gemini worker slot (16) is not.
  - The partial text of a stopped or failed answer is not kept on screen.
  - P3, open: no test for the stale message count that `populate_existing` prevents (Slice 3.2).
- **Commit / push:** `fix(chat)` commit on `slice-3.4`, merged into `main` and pushed. Branches `slice-3.1` and `slice-3.4` deleted.
- **Also added:** `backend/scripts/chat_check.py`, the Phase 3 real-provider check (used in the next step).
- **Next smallest task:** the Phase 3 exit gate, then Slice 4.1

### Slice 4.1 — Secure upload and source records
- **Date:** 2026-11-27 (owner away; worked autonomously, decisions below are assumptions)
- **What changed:** Members upload PDF, DOCX, TXT and Markdown files to an agent (`POST .../agents/<id>/sources`, the file as the raw body, its name percent-encoded in `X-File-Name`), list them, read one's status, and delete them. The type is decided by the content; the extension and declared type must agree. SVG and HTML are refused by name, declared type and content; PDFs naming `/JavaScript`, `/JS` or `/Launch`, DOCX with macros, encrypted entries, too many entries or bomb ratios are refused. 10 MB per file (checked before and while reading), 200 MB per workspace (under the workspace lock), 100 sources per agent, the same content once per agent, 30 uploads per person and 100 per workspace per hour. Files are stored under 32 random hex characters in `backend/var/knowledge` (ignored by git; any other folder inside the repository is refused), created exclusively with mode 0600. No route returns a file. Deleting a source, its agent or its workspace removes the files; `scripts.sweep_knowledge_files` removes files without a record that are over an hour old. File names and contents are never logged. Migration `0009`.
- **Assumptions (owner away):** sources are shared by the workspace like agents (any member uploads, lists, deletes); the raw body instead of multipart, so the body is counted while read; no download route; archived agents take no files, paused ones do; no interface yet (the guide puts "inspect and remove knowledge sources" in Slice 4.4); status values for 4.2 fixed now.
- **Plan:** `docs/plans/2026-11-27-1720-feat-secure-upload-plan.md`
- **Files/modules affected:** `backend/app/modules/knowledge/`, `backend/app/modules/{agents,workspaces,identity}/service.py` and `throttle.py`, `backend/app/core/config.py`, `backend/app/main.py`, `backend/migrations/versions/0009_knowledge_sources.py`, `backend/scripts/sweep_knowledge_files.py`, `backend/tests/`, `.gitignore`, `.gstack/pregate.json`, `backend/.env.example`, `docs/DATABASE_DESIGN.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PASS (1645, in 6 batches via `/verify`) | `backend: .venv\Scripts\python -m pytest`, in chunks | No skips |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Migration on dev DB | PASS | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head`, `check` | `0009` |
| Isolation matrix | PASS (423) | `test_tenant_isolation.py`, `test_route_inventory.py` | Every source route, with a real source of the other tenant and of a sibling agent |
| Test sensitivity | 39 of 39 caught | one guard at a time, one test file per process, in a copy | |
| Frontend | unchanged | | |

- **Review:** one independent Claude reviewer, reading only. No P0. Fixed: P1, an upload held a pooled database connection idle in a transaction while its body arrived (15 slow uploads would have blocked every request); P2, file names reached uvicorn's access log through the query string (now a header). Fixed P3s: a test that never reached the code it named, no test over the app-wide 64 KB body limit, a corrupt DOCX entry gave 500, the storage-folder guard allowed most of the repository (a public one), `/JS` followed by a line break passed. Recorded P3s below.
- **`/verify`:** `READY_FOR_SHIP tree=1a67b34b6427 checks=tests not_covered=none` (1,018 s). The first run failed one test, which lists every table and did not know the new one; fixed and run again.
- **Known limitations:**
  - P3, recorded: body chunks are written to disk on the event loop (bounded, small writes).
  - P3, recorded: a commit that fails after the server committed it would leave a record whose file was removed (rare; needs a connection loss during COMMIT).
  - P3, recorded: the DOCX limits trust the sizes the archive declares. Slice 4.2 must count the bytes it really unpacks.
  - The PDF script check is a heuristic: compressed objects or escaped names can hide a script. No stored file is ever served, so it cannot run here.
  - The storage cap counts stored files only, not their later chunks and vectors.
  - Orphan files are removed by a script, not on a schedule (the Slice 4.2 worker can run it).
- **Commit / push:** `feat(knowledge)` commit, merged into `main` and pushed; branch `slice-4.1` deleted.
- **Next smallest task:** Slice 4.2 — asynchronous document processing

### Slice 4.2 — Asynchronous document processing (local branch `slice-4.2`, committed, NOT verified, NOT pushed)
- **Date:** 2026-11-27 (owner away; decisions below are assumptions)
- **What changed:** An upload now enqueues a job in the same transaction (`jobs` table, ADR-0004). A separate worker (`python -m app.worker`) claims one job at a time with `FOR UPDATE SKIP LOCKED`, takes over jobs whose worker died once their lease ends, and turns the source into chunks of about 1,200 characters with 200 of overlap (`knowledge_chunks`), with page numbers for PDFs. Extraction runs in a child process with a 60 s timeout and a 512 MB memory cap: PDF with pypdf 7.2.0, DOCX streamed through expat with every DTD refused and the really unpacked bytes counted, TXT and Markdown as stored. Limits: 500 pages, 2,000,000 characters, 20 MB of DOCX XML. Statuses `pending` → `processing` → `ready` or `failed` with a fixed code and text (`text_empty` says that scans need text recognition, which does not exist). Failures that may pass are retried after 30 s and 2 min, at most 3 attempts; failures in the document are not. Re-running replaces a source's chunks; a source deleted meanwhile stays deleted. The worker also sweeps orphan files every 10 minutes. No document text in logs: the child's stderr is never read and log lines carry ids and codes. Migration `0010` also queues sources uploaded before it.
- **Assumptions (owner away):** pypdf for PDFs (pure Python, maintained, no dependencies); one child process per document; the worker is started by hand next to the API in development; no "reprocess" action (delete and upload again); chunk size 1,200/200.
- **Plan:** `docs/plans/2026-11-27-1900-feat-document-processing-plan.md`
- **Files/modules affected:** `backend/app/modules/jobs/`, `backend/app/modules/knowledge/{extract,chunking,processing,models,schemas,service}.py`, `backend/app/worker.py`, `backend/app/models.py`, `backend/migrations/versions/0010_jobs_and_knowledge_chunks.py`, `backend/requirements.txt`, `backend/constraints.txt`, `backend/tests/`, `.gstack/pregate.json`, `README.md`, `docs/DATABASE_DESIGN.md`, `docs/decisions/ADR-0004-background-jobs.md`
- **Tests run / results:**

| Check | Result | Command | Notes |
|---|---|---|---|
| Backend tests with real DB | PARTIAL | the files this slice touches | `test_processing.py` 36, `test_knowledge.py` 65, `test_migrations.py` 3, `test_run_tests_script.py` 9: all pass. The full suite was NOT run (see below) |
| Backend lint/format | PASS | `ruff check .`, `ruff format --check .` | |
| Migration on dev DB | PASS | `alembic upgrade head`, `check`, `downgrade -1`, `upgrade head`, `check` | `0010` |
| End to end, mock, dev DB | PASS | upload through the API, then the real worker process | A two-page PDF and a TXT became ready, a PDF without a text layer failed as `text_empty`; the worker log held no document text. It first found that the worker process could not resolve foreign keys (fixed) |
| Test sensitivity | INCOMPLETE: 3 of 3 caught, 22 not run | one guard at a time, one test file per process, in a copy | Stopped by Claude Code because the machine ran critically low on memory; not restarted, as instructed. Guard list: 25 |
| Frontend | unchanged | | |

- **Review:** one independent Claude reviewer, reading only. No P0. Fixed: P1 (a source whose attempts all died stayed "processing"), three P2s (UTF-16 passed the DTD byte check, a failing sweep killed the worker, no memory cap on the child) and five P3s. See the plan.
- **`/verify`:** NOT RUN, for the same reason. **Before merging:** run `/verify` (`gstack-checks run --timeout 2400`, which runs the whole backend suite 6 files per process) and the guard check, when memory allows.
- **Known limitations:**
  - The Windows memory cap is a watchdog thread that checks every 50 ms; a parser holding the interpreter lock for longer can overshoot it. POSIX uses `RLIMIT_AS`.
  - The PDF page tree is read by pypdf before the page limit applies; the time and memory caps bound that.
  - No OCR: scanned PDFs fail as `text_empty`.
  - Jobs are kept forever (small rows, no content); a cleanup comes when there are many.
  - No interface yet: statuses and reasons are in the API (`status`, `error_code`, `error_message`).
- **Commit / push:** committed on local branch `slice-4.2` only. Not merged and not pushed: the build guide requires the full suite and `/verify` first.
- **Next smallest task:** verify and merge this slice; Slice 4.3 is BLOCKED on pgvector
