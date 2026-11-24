# ADR-0005: Agent deletion permissions, cascade and usage records

- **Status:** Accepted (the conversation and execution cascade is provisional until Slice 3.2 builds it)
- **Date:** 2026-11-24

## Context

`docs/MASTER_PRD.md` AGT-1 lets any workspace member perform every agent operation, including delete. Deletion in this product is a hard delete (`docs/DATABASE_DESIGN.md`). An agent will later own conversations and executions, which may belong to several members. The PRD does not say what happens to them when the agent is deleted.

## Decision

1. **Only workspace owners can permanently delete an agent.** Members keep every other AGT-1 operation: create, list, view, edit, duplicate, pause, resume, archive and restore. A member who tries to delete gets 403. A non-member gets 404, as everywhere else (ADR-0001). This changes AGT-1 and the member row of the PRD roles table.
2. **Deleting an agent hard-deletes its configuration versions, conversations and executions** through database cascades. Slice 3.2 builds its schema to match, and later execution records follow the same rule.
3. **Usage rows survive deletion of agents, executions and workspaces.** They hold no user content: no prompts and no messages, only ids, token counts, cost and timestamps. Their foreign keys use `ON DELETE SET NULL`, never a cascade, and each row also keeps a plain, non-foreign-key copy of `workspace_id` and `user_id` for billing and audit. The usage slice implements this; Slice 2.1 only records it.

## Reason

Hard delete will also remove the agent's future conversations, so one member should not be able to wipe others' work. Members still have archiving, which can be undone. Billing and abuse audits need usage rows after the things they describe are gone.

## Alternatives considered

- Any member can delete (the PRD as written): one member could destroy others' work irreversibly.
- Refuse to delete an agent that has conversations: contradicts the existing hard-delete policy.
- Soft delete: needs retention rules and a purge job, and departs from the existing policy.

## Consequences

- Removing an agent a member created needs an owner.
- `docs/DATABASE_DESIGN.md` records the cascade when Slice 2.1 adds the tables.
- The usage slice builds its ledger to match decision 3, so no deletion of an agent, execution or workspace removes a usage row.
