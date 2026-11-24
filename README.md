# Agently

**Build Your Own AI. Put It to Work.**

Agently is a multi-tenant SaaS where people create their own AI agents, give them instructions and private knowledge, and use them from one workspace. See [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) and [docs/MASTER_PRD.md](docs/MASTER_PRD.md). Current progress: [PROJECT_STATUS.md](PROJECT_STATUS.md).

> Status: early development (Phase 1 — SaaS foundation). Accounts, workspaces and the dashboard work; agents do not exist yet.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI API (Python) |
| `frontend/` | Next.js web app (TypeScript, Tailwind) |
| `docs/` | Product, architecture, and decision records |
| `docker-compose.yml` | Optional local PostgreSQL |

## Prerequisites

- Python 3.12+ (developed on 3.14)
- Node.js 20+ and npm (developed on Node 24)
- PostgreSQL 16+ — native install, or Docker via `docker-compose.yml`

## Setup

### 1. Database

Native PostgreSQL — create a role and database (run in `psql` as a superuser; choose your own password):

```sql
CREATE ROLE agently LOGIN PASSWORD 'choose-a-local-password' CREATEDB;
CREATE DATABASE agently OWNER agently;
```

Or with Docker (listens on port 5433):

```powershell
docker compose up -d db
```

### 2. Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt -c constraints.txt
Copy-Item .env.example .env   # then edit DATABASE_URL
.venv\Scripts\alembic upgrade head            # create/upgrade the schema
.venv\Scripts\python -m scripts.seed_dev      # optional: DEVELOPMENT-only demo user + workspace
.venv\Scripts\uvicorn app.main:app --reload --port 8000 --no-proxy-headers
```

The seed script creates `demo@agently.local` with a random password that it prints once. It is safe to re-run, and refuses to run when `ENVIRONMENT` is `production` or unset, or when `DATABASE_URL` is not a local database. To get a new password, delete that user and its Demo Workspace, then run it again. **Databases seeded before Slice 1.2 still have the old published password**: do this on any you keep.

`--no-proxy-headers` is required: without it uvicorn lets a client choose its own IP address through `X-Forwarded-For`, which bypasses the login and signup limits. Schema and deletion rules: `docs/DATABASE_DESIGN.md`.

macOS/Linux: use `.venv/bin/...` and `cp`.

### 3. Frontend

```powershell
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. The page shows a **System status** panel that reports whether the API and database are reachable, with guidance if not. The frontend proxies `/api/*` to `BACKEND_URL` (default `http://127.0.0.1:8000`).

## Health endpoints

| Endpoint | Meaning |
|---|---|
| `GET /api/health` | Process is up (200 `{"status":"ok"}`) |
| `GET /api/health/ready` | Dependencies ready: 200 `ready`, or 503 `not_ready` with `checks.database` = `not_configured` / `unavailable` |

## Authentication endpoints

| Endpoint | Result |
|---|---|
| `POST /api/auth/register` | 201 and a session cookie. 409 `registration_failed`, 422, or 429 |
| `POST /api/auth/login` | 200 and a new session cookie. 401 `invalid_credentials`, 422, or 429 |
| `POST /api/auth/logout` | 204; revokes the session on the server and clears the cookie |
| `GET /api/auth/me` | The signed-in user, or 401 |

Pages: `/register`, `/login`, `/account`. Sign-in opens `/dashboard`, which redirects to the workspace last used in that browser (only its id is stored, under the user's id). State-changing requests need an `Origin` header listed in `ALLOWED_ORIGINS` (otherwise 403 `origin_rejected`), so `curl` and the interactive API docs on port 8000 are rejected unless you add that header or origin. Design: `docs/decisions/ADR-0003-session-authentication.md`.

Auth settings are in `backend/.env.example`. `ENVIRONMENT` defaults to `production` (fail safe), so `backend/.env` must set `ENVIRONMENT=development` for local work, as the example file does. If yours is older than Slice 1.2, also add `SIGNUP_LIMIT_PER_IP=100` and `LOGIN_LIMIT_PER_IP=200` before re-running the browser check often. Production must set `ALLOWED_ORIGINS` and `TRUSTED_PROXY_HOPS`, and run uvicorn with `--no-proxy-headers`.

## Workspace endpoints

| Endpoint | Who | Result |
|---|---|---|
| `GET`, `POST /api/workspaces` | signed in | List your workspaces; create one (at most 20 owned) |
| `GET /api/workspaces/{id}` | member | Name and your role |
| `PATCH`, `DELETE /api/workspaces/{id}` | owner | Rename; delete permanently |
| `POST /api/workspaces/{id}/leave` | member | Leave (not the last owner) |
| `GET /api/workspaces/{id}/members` | member | List members |
| `PATCH`, `DELETE /api/workspaces/{id}/members/{user_id}` | owner | Change role; remove |

Non-members get 404, members without the owner role get 403, and breaking the last-owner or 20-workspace rule gets 409. Registration creates a personal workspace. People cannot be invited yet. Pages: `/workspaces` (list and create), `/workspaces/<id>` (dashboard), `/workspaces/<id>/settings` (members, delete).

API docs (non-production): http://localhost:8000/api/docs

## Tests and checks

Backend (from `backend/`):

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\alembic check   # models and migrations in sync
```

Database tests need `DATABASE_URL` (the `agently` role needs `CREATEDB`). They create and drop their own `agently_test` / `agently_migrations_scratch` databases and never touch your dev database. Without `DATABASE_URL` they are skipped, and pytest ends with `N database tests SKIPPED: DATABASE_URL not set`. That is not a pass. To check this locally even though `backend/.env` exists, run from Git Bash: `DATABASE_URL= .venv/Scripts/python -m pytest`. Windows PowerShell 5.1 deletes a variable set to `""`, so `.env` would be used instead.

Frontend (from `frontend/`):

```powershell
npm test
npm run lint
npm run typecheck
npm run build
```

Browser checks of the auth, workspace and dashboard journeys (frontend and backend running, from the repository root; needs the Playwright skill, adds nothing to the frontend). Each run deletes the accounts it registered; after an interrupted run, use `.venv\Scripts\python -m scripts.delete_check_accounts --all` from `backend/`:

```powershell
node "$HOME\.claude\plugins\cache\playwright-skill\playwright-skill\5.0.0\skills\playwright-skill\run.js" docs/manual-checks/auth-browser-check.js
node "$HOME\.claude\plugins\cache\playwright-skill\playwright-skill\5.0.0\skills\playwright-skill\run.js" docs/manual-checks/workspace-browser-check.js
node "$HOME\.claude\plugins\cache\playwright-skill\playwright-skill\5.0.0\skills\playwright-skill\run.js" docs/manual-checks/dashboard-browser-check.js
```

## Shutdown

Stop the dev servers with `Ctrl+C`. Docker database: `docker compose down` (add `-v` only if you want to delete local data).

## Troubleshooting

- **System status says "database is not configured"** — create `backend/.env` from `.env.example` and set `DATABASE_URL`.
- **"database is not reachable"** — check PostgreSQL is running (`pg_isready -h localhost`) and the credentials in `DATABASE_URL`.
- **"API is not reachable"** — start the backend on port 8000 or set `BACKEND_URL` in `frontend/.env.local`.
- **`npm install` hangs** — retry with `npm install --fetch-timeout=60000 --fetch-retries=3`.

## Security

Never commit `.env` files or keys; the repository is public. Authentication rules: `docs/decisions/ADR-0003-session-authentication.md`. A general `docs/SECURITY.md` is not written yet.
