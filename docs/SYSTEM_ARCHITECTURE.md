# System Architecture

## 1. Shape

A **modular monolith**: one FastAPI backend process (plus a worker process from Phase 4 using the same codebase), one Next.js frontend, one PostgreSQL database. No microservices, Kubernetes, or event bus.

```text
Browser ──HTTPS──► Next.js frontend (UI, server components)
                     │  /api/*  rewrite (same origin → cookies stay first-party)
                     ▼
                  FastAPI backend ── SQLAlchemy ──► PostgreSQL (+ pgvector, Phase 4)
                     │                                  ▲
                     ├─► Model provider adapter ──► Anthropic API (3.1) / mock
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
2. Workspace-scoped routes take `workspace_id` in the path; a `workspace_context` dependency (`get_workspace_context`, `app/modules/workspaces/dependencies.py`) resolves the membership for `(current_user, workspace_id)`; absence → 404, the same as for a workspace that does not exist. `tests/test_tenant_isolation.py` fails for any route that neither uses it nor is on an explicit allowlist. Members get 403 for owner-only actions. The current workspace is the id in the URL; nothing is stored in the session.
3. Services receive the resolved context and filter every query by `workspace_id`.
4. Role checks use a server-side role→permission map.

## 5. Authentication (see ADR-0003)

Server-side sessions: opaque random token in an `HttpOnly`, `SameSite=Lax` cookie that is `Secure` everywhere except development; only the SHA-256 hash is stored. Passwords hashed with Argon2id. Every state-changing request requires an allowlisted `Origin` header as CSRF defence (`app/core/origin_guard.py`).

Every route depends on `get_current_user` unless it is listed in `PUBLIC_ROUTES` (`app/modules/identity/router.py`); `tests/test_route_inventory.py` enforces this.

Login and signup throttling counts rows in `auth_throttle_events`. The client IP is the socket peer unless `TRUSTED_PROXY_HOPS` says how many proxies append to `X-Forwarded-For`. Uvicorn must always run with `--no-proxy-headers`; by default it overwrites the peer from that header for local connections. IPv6 clients are throttled by /64. The Next.js rewrite forwards a client-sent `X-Forwarded-For` unchanged, so it is never a trusted hop: with Next.js as the only proxy, all users share one IP bucket. Production needs an edge proxy that appends the real client address, and only the proxies may reach the backend.

## 6. Errors

All errors use `{"error": {"code": "<stable_code>", "message": "<safe text>", "details": ..., "request_id": "..."}}`. Unexpected errors are logged with the request ID and return a generic message.

## 7. Model providers and generated drafts

`app/modules/providers` defines the only way to call a model: a list of system, user and assistant messages, a timeout and a maximum of output tokens go in; text and token counts come out. Configuration chooses the provider, never a request. Slice 3.1 adds streaming and a real adapter.

`app/modules/agent_builder` turns a person's answers into a draft and cannot save one. Answers and model output are both untrusted:

- The whole prompt is in `prompt.py`, with an exact snapshot in `backend/tests/snapshots/`. Answers are escaped inside `<user_answer>` tags and never enter the system message.
- Output must be one JSON object with exactly four text fields within the agent limits, without duplicate keys or hidden characters. Anything else is rejected whole.
- No database connection is held during the call, and at most 8 calls run at once per process. Answers, prompts, output and provider errors are neither stored nor logged.
- Schema checks cannot judge what instructions say. The person's review does, and agents have no permissions a draft could grant.

## 8. Configuration and secrets

All configuration via environment variables (`.env` locally, never committed). `.env.example` contains placeholders only. Provider keys are server-side only.

## 9. Local development services

- PostgreSQL (native install or `docker compose up db`).
- Backend: `uvicorn app.main:app --reload --no-proxy-headers` on port 8000.
- Frontend: `npm run dev` on port 3000, proxying `/api/*` to the backend.

## 10. Deployment shape (initial)

Two containers (frontend, backend) + managed PostgreSQL + S3-compatible storage. Detailed in Phase 6.
