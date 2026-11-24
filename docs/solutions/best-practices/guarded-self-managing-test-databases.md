---
title: Guard self-managing test databases by name, and by what the driver actually connects to
date: 2026-11-21
category: best-practices
module: backend
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - "A test fixture creates, drops, or migrates databases on a developer's real PostgreSQL server"
  - "Adding a new throwaway database name or changing how test database URLs are derived"
tags: [pytest, postgresql, test-database, drop-guard, data-loss, alembic]
---

# Guard self-managing test databases by name, and by what the driver actually connects to

## Context

Slice 1.1 made the test suite create and drop its own databases (`agently_test` per run, a fresh `agently_migrations_scratch` per migration test). It ends its own role's client connections, then drops the database with retries (until 2026-11-24 it used `DROP DATABASE ... WITH (FORCE)`, which fails with "permission denied" when another role's process is connected), on the same PostgreSQL server that holds the dev `agently` database and other projects' databases (`urbanpulse`, `urbanpulse_test`). A mistake in this harness means permanent data loss on the owner's machine, so the owner required the dev database to be impossible to drop from tests.

## Guidance

The pattern in `backend/tests/db_utils.py` and `backend/tests/conftest.py`:

- **One choke point.** `recreate_database` and `drop_database` are the only code that issues CREATE/DROP. Both call `assert_disposable_name` first. It refuses any name not ending in `_test` or `_scratch`, and any name with characters other than letters, digits and `_`. Identifiers can't be bound parameters, so that character check is what keeps the f-string DDL safe.
- **Guard before connecting.** The guard runs before any engine is created. `test_db_guard.py` proves this by pointing at an unreachable URL (`127.0.0.1:1`). If a guard were missing, the test would see a connection error, not `UnsafeDatabaseNameError`.
- **Fixed constant names, never from the environment.** The suffix rule alone would allow `urbanpulse_test`. Fixtures only ever pass `TEST_DATABASE_NAME` and `SCRATCH_DATABASE_NAME`, so another project's `_test` database is never touched.
- **Guard the effective target, not just the requested name.** psycopg lets a `?dbname=` or `?database=` query parameter override the URL path. Before the fix, `sibling_url(".../agently?dbname=agently", "agently_test")` printed as `agently_test` but connected to `agently`. The migration test's downgrade would then have wiped the dev schema. `sibling_url` now strips those keys. `test_derived_url_cannot_be_redirected_by_query_parameters` checks the dialect's real connect arguments (`create_connect_args`), not the URL string. Any new way of deriving a URL needs the same driver-level assertion.
- **Prove the tests can fail.** After writing the schema tests, the migration was broken in place, with the workspace cascade and the `lower(email)` index removed. Three tests failed, and the file was restored. Tests that only ever passed proved nothing about the guard or the constraints.

## Why This Matters

The name guard looked complete, and an inline review passed it. The `?dbname=` bypass only showed up when an independent adversarial reviewer asked what the driver *does* with the URL. Confirming it took a two-line `create_connect_args` probe. A name guard on the string you build is not the same thing as a guard on the database you end up connected to.

## When to Apply

Known open limits, not fixed in Slice 1.1. Revisit them before they bite:

- **Concurrent runs collide: fixed 2026-11-24.** Fixed names plus ending existing connections meant two pytest runs on one server dropped each other's databases, seen as `KeyError` and "server closed the connection" in unrelated tests. A run now holds an advisory lock and a second one stops with a clear message. Advisory locks belong to one database, so it is taken in `postgres`, where the drops cannot end its connection.
- **No host check.** If `DATABASE_URL` points at a shared or staging server whose role has `CREATEDB`, the suite creates and drops its two databases *there*.
- **An all-skipped run still exits 0.** The loud summary line is the only signal, so CI must require the DB tests to actually run, for example with a strict mode that fails when they were skipped.
- **Unmarked DB tests skip silently.** A test that uses the `database_url` fixture without `@pytest.mark.db` skips without being counted in the summary.

## Related

- `docs/DATABASE_DESIGN.md`, "Tests" section
- [PowerShell empty env var deletes the variable](../developer-experience/powershell-empty-env-var-deletes-variable.md): the other way a DB-test check can report the opposite of the truth
