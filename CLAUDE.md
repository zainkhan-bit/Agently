# CLAUDE.md — Agently

## Source of truth (read in this order)
1. `AGENT_BUILD_GUIDE.md` — master rules: one verified slice at a time, Definition of Done, commit/push policy, when to stop and ask.
2. `PROJECT_STATUS.md` — current milestone, next smallest task, blockers. Update it after every slice.
3. `docs/MASTER_PRD.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/decisions/` — scope, architecture, ADRs.

If any plugin or skill below suggests a workflow that conflicts with `AGENT_BUILD_GUIDE.md`, the guide wins.

## Stack
- Backend: FastAPI (Python 3.12+), `backend/` — tests `pytest`, lint `ruff check .`, format `ruff format --check .`
- Frontend: Next.js 15 + TypeScript + Tailwind 4, `frontend/` — `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`
- DB: PostgreSQL (pgvector), SQLAlchemy + Alembic (Phase 1)
- Dev OS: Windows (PowerShell). Use `.venv\Scripts\...` paths in instructions.
- Repo is PUBLIC: never commit `.env`, keys, tokens, or `AUDIT.md`.

## Tools installed for this project

### Compound Engineering (plugin) — plan → work → review → compound
Use for any slice bigger than a one-file change:
```
/ce-brainstorm <slice goal>
/ce-plan
/ce-work
/ce-code-review
/ce-compound        # saves learnings to docs/solutions/
```
Do NOT use `/lfg` (hands-off mode) on this repo — the build guide requires each slice to be tested and logged in PROJECT_STATUS.md before commit.

### claude-mem (plugin) — memory across sessions
Runs automatically. Stored locally in `~/.claude-mem/`. Never paste secrets into a session (they could be captured in memory).

### Playwright skill (plugin) — real browser testing
Use to verify UI slices end-to-end, e.g.:
"Use Playwright to open http://localhost:3000, check the System status panel, and screenshot each state."
Requires frontend (`npm run dev`) and backend (port 8000) running.

### Graphify — codebase knowledge graph
Rebuild after big changes: `/graphify .` → open `graphify-out/graph.html`.
Prefer querying the graph over grepping many files when answering "how does X flow" questions.

## Security audit before launch
`.audit/pre-launch-security-audit.pdf` (gitignored, third-party doc).
It was written for Emergent apps (React/FastAPI/MongoDB). For Agently, apply the checks that fit our stack: treat MongoDB items as PostgreSQL/SQLAlchemy equivalents (parameterised queries, ownership filters, workspace scoping), ignore Emergent-specific items (Emergent Auth, EMERGENT_LLM_KEY, Expo).
Run it only when the owner says "start the security audit". Findings go to `AUDIT.md` (gitignored). Never print full secrets.
