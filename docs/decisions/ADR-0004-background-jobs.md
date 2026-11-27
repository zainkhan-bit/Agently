# ADR-0004: PostgreSQL-backed background jobs

- **Status:** Accepted; implemented in Slice 4.2 (2026-11-27): `backend/app/modules/jobs/`, `backend/app/worker.py`
- **Date:** 2026-11-20

## Context

Document processing and embeddings (Phase 4) must run outside request handlers. The guide suggests Redis + Celery "or a comparably simple maintained queue". Redis and Docker are not installed on the dev machine, and adding Redis means another service to run, secure, and monitor.

## Decision

Use a `jobs` table in PostgreSQL and a worker process that claims jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, with attempt counts, bounded retries with backoff, timeouts, and idempotency keys. The worker shares the backend codebase.

## Alternatives considered

- Redis + Celery: mature, but adds infrastructure for a workload of a few jobs per upload.
- FastAPI `BackgroundTasks`: in-process, lost on restart, no retries.

## Consequences

One fewer service. If throughput later demands it, the job interface can be backed by a dedicated queue without changing callers.
