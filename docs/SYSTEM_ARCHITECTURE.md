# System Architecture

## 1. Shape

A **modular monolith**: one FastAPI backend process (plus a worker process from Phase 4 using the same codebase), one Next.js frontend, one PostgreSQL database. No microservices, Kubernetes, or event bus.

```text
Browser ──HTTPS──► Next.js frontend (UI, server components)
                     │  /api/*  rewrite (same origin → cookies stay first-party)
                     ▼
                  FastAPI backend ── SQLAlchemy ──► PostgreSQL (+ pgvector, Phase 4)
                     │                                  ▲
                     ├─► Model provider adapter ──► Anthropic API / mock
                     └─► Local file storage (dev) / S3-compatible (prod)
                  Worker (Phase 4) ── polls jobs table in PostgreSQL ─┘
```

## 2. Stack (see ADR-0002)

| Layer | Choice |
|---|---|
| Backend | Python 3.12+ (dev machine: 3.14), FastAPI, Pydantic v2, pydantic-settings |
| ORM / migrations | SQLAlchemy 2.x, Alembic |
| DB driver | psycopg 3 |
| Database | PostgreSQL 16+ (dev machine: 18); pgvector in Phase 4 |
| Background jobs | PostgreSQL-backed job table + worker (ADR-0004) |
| Frontend | Next.js (App Router) + TypeScript + Tailwind CSS |
| Backend tests | pytest, httpx TestClient, real PostgreSQL test database |
| Frontend tests | Vitest + Testing Library; Playwright for critical journeys |
| Lint/format | ruff (Python), ESLint + TypeScript (`tsc --noEmit`) |
| Packages | pip + venv with pinned `requirements*.txt`; npm with `package-lock.json` |

## 3. Backend module layout

```text
backend/app/
  main.py               # app factory, routers, middleware
  core/                 # config, database session, security, logging, errors
  modules/<module>/     # models.py, schemas.py, service.py, router.py
  shared/               # permissions, pagination, common schemas
backend/migrations/     # Alembic (schema + deletion rules: docs/DATABASE_DESIGN.md)
backend/tests/
```

Routes authenticate, validate, and call a service. Services own business rules and tenant scoping. The agent runtime (Phase 3) is a service, never inside route handlers.

## 4. Request flow and tenant scoping

1. Session cookie → `current_user` dependency (DB lookup of hashed session token, expiry check).
2. Workspace-scoped routes take `workspace_id` in the path; a `workspace_context` dependency resolves the membership for `(current_user, workspace_id)`; absence → 404.
3. Services receive the resolved context and filter every query by `workspace_id`.
4. Role checks use a server-side role→permission map.

## 5. Authentication (see ADR-0003)

Server-side sessions: opaque random token in an `HttpOnly`, `SameSite=Lax`, `Secure`-in-production cookie; only the SHA-256 hash is stored. Passwords hashed with Argon2id. Mutating requests require a matching `Origin` (or `X-Requested-With`) as CSRF defence.

## 6. Errors

All errors use `{"error": {"code": "<stable_code>", "message": "<safe text>", "details": ..., "request_id": "..."}}`. Unexpected errors are logged with the request ID and return a generic message.

## 7. Configuration and secrets

All configuration via environment variables (`.env` locally, never committed). `.env.example` contains placeholders only. Provider keys are server-side only.

## 8. Local development services

- PostgreSQL (native install or `docker compose up db`).
- Backend: `uvicorn app.main:app --reload` on port 8000.
- Frontend: `npm run dev` on port 3000, proxying `/api/*` to the backend.

## 9. Deployment shape (initial)

Two containers (frontend, backend) + managed PostgreSQL + S3-compatible storage. Detailed in Phase 6.
