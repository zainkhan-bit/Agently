---
title: PowerShell 5.1 `$env:VAR=""` deletes the variable, so `.env` fallbacks silently win
date: 2026-11-21
category: developer-experience
module: backend
problem_type: developer_experience
component: development_workflow
severity: medium
applies_when:
  - "Verifying a code path that should run when a setting is empty or unset, from Windows PowerShell"
  - "A setting is loaded with pydantic-settings and backend/.env also defines it"
tags: [windows, powershell, environment-variables, pydantic-settings, dotenv, testing]
---

# PowerShell 5.1 `$env:VAR=""` deletes the variable, so `.env` fallbacks silently win

## Context

During Slice 1.1 the plan's "skip honesty" check was: run pytest with `DATABASE_URL` empty and expect the database tests to skip with `N database tests SKIPPED: DATABASE_URL not set`. Running `$env:DATABASE_URL=""; .venv\Scripts\python -m pytest` in Windows PowerShell 5.1 printed `44 passed`. No skip line appeared, and a following `Remove-Item Env:DATABASE_URL` failed with "Cannot find path 'Env:\DATABASE_URL'".

PowerShell 5.1 treats assigning an empty string to `$env:NAME` as *removing* the variable. With the variable absent, `Settings` (`backend/app/core/config.py`, `env_file=".env"`) loaded `DATABASE_URL` from `backend/.env`, and every database test ran against the real server. The manual check reported the opposite of what it was meant to prove. It looked like the skip path worked, but the skip path never ran.

This was observed on Windows PowerShell 5.1. PowerShell 7 was not checked.

## Guidance

To get a truly empty value, which pydantic-settings uses ahead of the `.env` file:

- **Git Bash:** `DATABASE_URL= .venv/Scripts/python -m pytest` (verified: 23 passed, 21 skipped, summary line printed).
- **Python subprocess:** `subprocess.run(..., env={**os.environ, "DATABASE_URL": ""})`. `backend/tests/test_skip_summary.py` uses this form, so the automated check is not affected.
- **PowerShell:** don't use `$env:X=""` to mean "empty". Use Git Bash or a Python wrapper instead.

The application side treats an empty value as unset (`get_engine` in `backend/app/core/database.py`, `configured_database_url` in `backend/tests/conftest.py`), so an empty value means "not configured" and does not reach `create_engine("")`.

After any manual "unset/empty" check, check the *output* for the expected signal (here, the skip line). A green run by itself proves nothing.

## Why This Matters

Any future check of a "setting missing" path has the same trap: model-provider API keys (Phase 2/3), feature flags, rate-limit settings. In PowerShell the check quietly falls back to `backend/.env` and passes for the wrong reason. Separately, `env_file=".env"` resolves against the current directory, so running pytest from the repo root does not load `backend/.env` at all. That is the opposite trap: the database tests skip when you expected them to run.

## When to Apply

- Writing verification steps or README instructions that set a variable to empty on Windows.
- Reviewing a test result where "everything passed" was supposed to include skips.

## Related

- `README.md`, "Tests and checks": documents the Git Bash form for this repo.
- `PROJECT_STATUS.md`, Slice 1.1 entry: records the PASS/SKIPPED rows that came from the corrected run.
