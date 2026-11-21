# Agently

**Build Your Own AI. Put It to Work.**

Agently is a multi-tenant SaaS where people create their own AI agents, give them instructions and private knowledge, and use them from one workspace. See [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) and [docs/MASTER_PRD.md](docs/MASTER_PRD.md). Current progress: [PROJECT_STATUS.md](PROJECT_STATUS.md).

> Status: early development (Phase 0 — foundation). Only health checks and an app shell exist so far.

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
.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

The seed script creates `demo@agently.local` / `agently-demo-password` (a public dev-only credential), is safe to re-run, and refuses to run when `ENVIRONMENT=production`. Schema and deletion rules: `docs/DATABASE_DESIGN.md`.

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

## Shutdown

Stop the dev servers with `Ctrl+C`. Docker database: `docker compose down` (add `-v` only if you want to delete local data).

## Troubleshooting

- **System status says "database is not configured"** — create `backend/.env` from `.env.example` and set `DATABASE_URL`.
- **"database is not reachable"** — check PostgreSQL is running (`pg_isready -h localhost`) and the credentials in `DATABASE_URL`.
- **"API is not reachable"** — start the backend on port 8000 or set `BACKEND_URL` in `frontend/.env.local`.
- **`npm install` hangs** — retry with `npm install --fetch-timeout=60000 --fetch-retries=3`.

## Security

Never commit `.env` files or keys; the repository is public. See `docs/SECURITY.md` (added in Phase 1).
