# ADR-0003: Server-side session authentication

- **Status:** Accepted
- **Date:** 2026-11-20 (amended 2026-11-23 by Slice 1.2)

## Context

The MVP needs registration, login, logout, and session retrieval with revocation (guide 5.1). No external identity provider or email service is configured.

## Decision

- Passwords are hashed with **Argon2id** (`argon2-cffi`).
- On login, the server generates a 256-bit random token, stores only its **SHA-256 hash** in a `sessions` table with `expires_at`, and sets it in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` in every environment except `development`; production refuses to start otherwise, and an unset `ENVIRONMENT` means production). Sessions last 14 days from creation and are never extended.
- Logout sets `revoked_at` on the session row, so revocation is immediate.
- The frontend reaches the backend through a same-origin `/api` rewrite, keeping the cookie first-party.
- CSRF: `SameSite=Lax` blocks cross-site POSTs from carrying the cookie; in addition, every state-changing request, including login and register, must carry exactly one `Origin` header from the `ALLOWED_ORIGINS` list. A missing header is rejected, and no other header substitutes for it.
- Login and signup are throttled with 429 from counters in PostgreSQL; accounts are never locked. Failed logins are limited per account-and-IP pair (5), per account across all IPs (50), and per IP (20) every 15 minutes; signups per IP (5) every hour. A successful login clears the account's counters, never the IP's.
- Email verification and password reset are **not built** until an email service is configured (guide 1.2: do not fake them).

## Alternatives considered

- JWT access tokens: harder to revoke; no benefit for a single backend.
- Hosted auth providers: require external accounts/credentials the owner has not provided.

## Consequences

Each authenticated request does one indexed DB lookup. Sessions can be listed and revoked per user later.

Accepted risks: registering an email that already exists reveals that it exists (no email verification yet; signup throttling limits probing). An attacker using several IPs (including one subscriber with several IPv6 /64 networks) can reach the per-account ceiling and block that account's login while the attack lasts; the alternative, a single strict per-account limit, would let one IP do it.
