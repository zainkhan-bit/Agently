# ADR-0003: Server-side session authentication

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

The MVP needs registration, login, logout, and session retrieval with revocation (guide 5.1). No external identity provider or email service is configured.

## Decision

- Passwords are hashed with **Argon2id** (`argon2-cffi`).
- On login, the server generates a 256-bit random token, stores only its **SHA-256 hash** in a `sessions` table with `expires_at`, and sets it in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when `ENVIRONMENT=production`).
- Logout deletes the session row, so revocation is immediate.
- The frontend reaches the backend through a same-origin `/api` rewrite, keeping the cookie first-party.
- CSRF: `SameSite=Lax` blocks cross-site POSTs from carrying the cookie; in addition, mutating requests with a session must carry an allowed `Origin` header when one is present.
- Email verification and password reset are **not built** until an email service is configured (guide 1.2: do not fake them).

## Alternatives considered

- JWT access tokens: harder to revoke; no benefit for a single backend.
- Hosted auth providers: require external accounts/credentials the owner has not provided.

## Consequences

Each authenticated request does one indexed DB lookup. Sessions can be listed and revoked per user later.
