# ADR-0002: Technology stack

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

The repository was empty, so there was no existing stack to preserve. The guide (Section 4.1) recommends Next.js + TypeScript, FastAPI, PostgreSQL, SQLAlchemy 2, Alembic, pgvector, and a simple queue. The dev machine has Python 3.14, Node 24, and PostgreSQL 18 natively, but no Docker.

## Decision

Adopt the guide's preferred stack with these specifics:

- **Backend:** FastAPI + Pydantic v2 + SQLAlchemy 2 (sync sessions) + Alembic + psycopg 3. Sync SQLAlchemy keeps code simple; FastAPI runs sync endpoints in a threadpool. Streaming endpoints can use async generators independently.
- **Frontend:** Next.js App Router + TypeScript + Tailwind. Component primitives are written in-house on Tailwind (shadcn-style) rather than adding a component library until needed.
- **Package managers:** pip + venv with fully pinned requirements (one per environment), and npm with a committed `package-lock.json`. pnpm is also installed on the machine but npm is the default that ships with Node, reducing setup steps.
- **Tests:** pytest against a real PostgreSQL test database (not SQLite) so constraints, types, and later pgvector behave as in production; Vitest + Testing Library; Playwright for end-to-end.
- **Lint:** ruff for Python; ESLint + `tsc --noEmit` for TypeScript.
- **Docker Compose:** provided for PostgreSQL as an optional path; native PostgreSQL is the verified path on the current dev machine.

## Alternatives considered

- Async SQLAlchemy: more complex session handling, little benefit at MVP scale.
- SQLite for tests: diverges from PostgreSQL behaviour (constraints, JSONB, pgvector).
- Poetry/uv: not installed; pinned requirements are sufficient and universally available.

## Consequences

Python 3.14 is new; dependencies are pinned to versions that ship 3.14 wheels. CI will use a pinned Python version.
