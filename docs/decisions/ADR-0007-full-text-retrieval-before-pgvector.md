# ADR-0007: Full-text retrieval before pgvector

- **Status:** Accepted; implemented in Slice 4.3 (2026-11-28): `backend/app/modules/knowledge/retrieval.py`, migration `0011`
- **Date:** 2026-11-28
- **Deviates from:** [ADR-0002](ADR-0002-technology-stack.md), which chose pgvector for retrieval

## Context

Slice 4.3 asks for embeddings and vector retrieval with pgvector. The pgvector extension is not available on the local PostgreSQL 18.6 (`pg_available_extensions` has no `vector` row). Installing it on Windows needs administrator rights and the Visual Studio C++ build tools, and the owner decided on 2026-11-28 not to install it now. Slice 4.4 (grounded answers) and the Phase 4 exit gate need retrieval, so waiting would block Phase 4.

## Decision

Retrieval goes behind one interface, with PostgreSQL full-text search as its first implementation. pgvector stays the production target.

- **The interface.** Callers use only `get_retriever()` and the `Excerpt` value: source id, source name, page, sequence and text, in rank order. There is no score, because full-text ranks and embedding similarities are on different scales and must not be compared or used as thresholds.
- **The index.** `knowledge_chunks` has two generated, stored `tsvector` columns, each with a GIN index: `to_tsvector('english', content)` (stemmed English) and `to_tsvector('simple', content)` (exact words, for Roman Urdu and other words English stemming does not know). PostgreSQL fills them, including for chunks that existed before migration `0011`, so the worker did not change.
- **Matching.** A chunk matches through either column. Every question word must match first. When that gives too few results, a second pass accepting any of the same words fills the remaining places, ranked below the first. Ranking is `ts_rank_cd`. English stop words are removed from the exact-word query, because the `simple` configuration keeps them and "the and of" would otherwise match nearly everything. User text reaches PostgreSQL only as plain word tokens, through `plainto_tsquery` or `websearch_to_tsquery`, never `to_tsquery`.
- **Scope.** Every query filters on the workspace, the agent and source status `ready`.

## Alternatives considered

- **Install pgvector locally now:** the owner declined (admin rights, C++ build tools).
- **Wait for pgvector:** blocks Slice 4.4 and the Phase 4 exit gate.
- **An embedding store outside PostgreSQL:** adds a service to run and secure, and ADR-0002's single-database choice still holds.
- **Exposing a score to callers:** callers that compare or threshold scores would break at the switch.

## Consequences

- Full-text search finds shared words only. A question phrased in other words than the document can return nothing, so Slice 4.4's "not found" answer will fire more often than it would with embeddings.
- Migration `0011` rewrites `knowledge_chunks` once while adding the stored columns. That is quick at development scale. A production database with many chunks should run it in a quiet window.

## What changes at the switch to pgvector

Listed under "Must fix before any deployment" in `PROJECT_STATUS.md`.

1. Install pgvector on the production database (and locally, following the steps kept in `PROJECT_STATUS.md`).
2. Add an embeddings table that refers to chunks by id. The full-text columns stay as they are.
3. Add a worker step that embeds chunks, with a replaceable embedding provider and a deterministic test double.
4. Add the embedding retriever and a setting that chooses between it and full-text search in `get_retriever()`. Callers and the endpoint response do not change.
5. Build the guide's Slice 4.3 items deferred to then: record the embedding model, version and dimensions; test that dimensions match the database column; give sources a clear processing status when embedding credentials are missing.
