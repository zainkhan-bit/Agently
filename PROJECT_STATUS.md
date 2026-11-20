# Project Status — Agently

**Current milestone:** Phase 1 — SaaS foundation (Phase 0 exit gate met)
**Next smallest task:** Slice 1.1 — database configuration, SQLAlchemy models, Alembic migrations for users/workspaces/memberships/sessions

## Blocked / needs owner input

- **Slice 1.1 (database) is BLOCKED on local PostgreSQL credentials.** PostgreSQL 18 is running on `localhost:5432` but requires a password the agent does not have. Owner action: create the `agently` role/database (README, Setup §1) and put `DATABASE_URL` in `backend/.env` (never committed).
- Later (Phase 2.3 / 3.1): a real model-provider API key is needed for real-provider smoke tests. Until then those tests are BLOCKED and a mock provider is used.

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
- **Commit / push:** see Slice 1.1 entry
- **Next smallest task:** Slice 1.1 (blocked on DB credentials)
