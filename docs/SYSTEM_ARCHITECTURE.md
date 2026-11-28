# System Architecture

## 1. Shape

A **modular monolith**: one FastAPI backend process (plus a worker process from Phase 4 using the same codebase), one Next.js frontend, one PostgreSQL database. No microservices, Kubernetes, or event bus.

```text
Browser ──HTTPS──► Next.js frontend (UI, server components)
                     │  /api/*  rewrite (same origin → cookies stay first-party)
                     ▼
                  FastAPI backend ── SQLAlchemy ──► PostgreSQL (full-text search now; pgvector before deployment, ADR-0007)
                     │                                  ▲
                     ├─► Model provider adapter ──► Gemini API / mock
                     └─► Local file storage (dev) / S3-compatible (prod)
                  Worker (Phase 4) ── polls jobs table in PostgreSQL ─┘
```

## 2. Stack (see ADR-0002)

| Layer | Choice |
|---|---|
| Backend | Python 3.12+ (dev machine: 3.14), FastAPI, Pydantic v2, pydantic-settings |
| ORM / migrations | SQLAlchemy 2.x, Alembic |
| DB driver | psycopg 3 |
| Database | PostgreSQL 16+ (dev machine: 18); retrieval by full-text search until pgvector is installed (ADR-0007) |
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

`app/modules/providers` defines the only way to call a model: a list of system, user and assistant messages, a timeout and a maximum of output tokens go in; text and token counts come out. A stream gives the text in pieces and ends with the same result; closing it cancels. Tool calls have a type, but nothing sends tools. Configuration chooses the provider, never a request (ADR-0006).

- **Gemini** (`gemini.py`): a worker thread does the network work and the caller waits with a deadline, so name lookups, slow connections and trickles of bytes cannot pass it. At most 16 workers; a stuck one keeps its place. No retries, redirects or proxies. The key is only in the `x-goog-api-key` header.
- **Spending** (`spending.py`): wraps every real provider. The worst case is reserved in `provider_spend` before a call, one reservation at a time, and corrected after success. Calls never sent, or refused with 401 to 404 or 429, give it back. Everything else keeps it. A warning is logged from 80% of either limit.
- **Logging** (`app/core/logs.py`): the HTTP libraries are silent at every `LOG_LEVEL`. Settings errors never repeat values.
- **Tests** switch the provider and key off before the app is imported and may connect to this computer only.

`app/modules/agent_builder` turns a person's answers into a draft and cannot save one. Answers and model output are both untrusted:

- The whole prompt is in `prompt.py`, with an exact snapshot in `backend/tests/snapshots/`. Answers are escaped inside `<user_answer>` tags and never enter the system message.
- Output must be one JSON object with exactly four text fields within the agent limits, without duplicate keys or hidden characters. Anything else is rejected whole.
- No database connection is held during the call, and at most 8 calls run at once per process. Answers, prompts, output and provider errors are neither stored nor logged.
- Schema checks cannot judge what instructions say. The person's review does, and agents have no permissions a draft could grant.

`app/modules/conversations` keeps private conversations (ADR-0005). `get_conversation` is the only way for a request to reach one, and it requires the creator; the isolation matrix fails for a route that names anything outside the shared ids without it, and lets teammates of both roles attack. `store_message` is internal: routes cannot choose a role or version. Responses are `private, no-store`.

`app/modules/runtime` answers messages: `docs/AI_RUNTIME.md`.

## 8. Configuration and secrets

All configuration via environment variables (`.env` locally, never committed). `.env.example` contains placeholders only. Provider keys are server-side only.

## 9. Local development services

- PostgreSQL (native install or `docker compose up db`).
- Backend: `uvicorn app.main:app --reload --no-proxy-headers` on port 8000.
- Frontend: `npm run dev` on port 3000, proxying `/api/*` to the backend.

## 10. Deployment shape (initial)

Two containers (frontend, backend) + managed PostgreSQL + S3-compatible storage. Detailed in Phase 6.
