# ADR-0005: Agent deletion permissions, cascade and usage records

- **Status:** Accepted. Slice 3.2 built the conversation cascade and added decisions 4 and 5 (2026-11-26); the execution cascade is provisional until executions exist
- **Date:** 2026-11-24

## Context

`docs/MASTER_PRD.md` AGT-1 lets any workspace member perform every agent operation, including delete. Deletion in this product is a hard delete (`docs/DATABASE_DESIGN.md`). An agent will later own conversations and executions, which may belong to several members. The PRD does not say what happens to them when the agent is deleted.

## Decision

1. **Only workspace owners can permanently delete an agent.** Members keep every other AGT-1 operation: create, list, view, edit, duplicate, pause, resume, archive and restore. A member who tries to delete gets 403. A non-member gets 404, as everywhere else (ADR-0001). This changes AGT-1 and the member row of the PRD roles table.
2. **Deleting an agent hard-deletes its configuration versions, conversations and executions** through database cascades. Slice 3.2 builds its schema to match, and later execution records follow the same rule.
3. **Usage rows survive deletion of agents, executions and workspaces.** They hold no user content: no prompts and no messages, only ids, token counts, cost and timestamps. Their foreign keys use `ON DELETE SET NULL`, never a cascade, and each row also keeps a plain, non-foreign-key copy of `workspace_id` and `user_id` for billing and audit. The usage slice implements this; Slice 2.1 only records it.

4. **A conversation is seen only by the person who started it.** Other members and owners get the same 404 as for one that does not exist (owner decision of 2026-11-26).
5. **Leaving or being removed from a workspace hard-deletes that person's conversations in it**, at once and for good, also when they are added again. Nobody else could reach or delete them. Deleting an account does the same everywhere (owner decision of 2026-11-26).

## Reason

Hard delete will also remove the agent's future conversations, so one member should not be able to wipe others' work. Members still have archiving, which can be undone. Billing and abuse audits need usage rows after the things they describe are gone.

## Alternatives considered

- Any member can delete (the PRD as written): one member could destroy others' work irreversibly.
- Refuse to delete an agent that has conversations: contradicts the existing hard-delete policy.
- Soft delete: needs retention rules and a purge job, and departs from the existing policy.

- Conversations visible to owners, or to all members: message text is private, and people would have to be told before they type.
- Keep the conversations of people who left, hidden: private text that nobody can reach or delete.

## Consequences

- An owner who deletes an agent or removes a member destroys conversations they cannot see. The interface must warn them before Slice 3.4 ships.
- Removing an agent a member created needs an owner.
- `docs/DATABASE_DESIGN.md` records the cascade when Slice 2.1 adds the tables.
- The usage slice builds its ledger to match decision 3, so no deletion of an agent, execution or workspace removes a usage row.
