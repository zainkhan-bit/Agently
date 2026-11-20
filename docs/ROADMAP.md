# Roadmap

Phases follow `AGENT_BUILD_GUIDE.md` Section 7. Each phase is built as small verified slices; progress is tracked in `PROJECT_STATUS.md`.

## MVP

| Phase | Scope | Exit gate |
|---|---|---|
| 0 | Repository audit, product spec, architecture, local dev setup | App runs reproducibly; docs exist |
| 1 | Database/migrations, auth, workspaces, dashboard shell | Secure login, workspace dashboard, isolation tests pass |
| 2 | Agent model/APIs, My Agents UI, prompt-to-agent builder, versioned config | Agents created/edited/paused; drafts schema-validated |
| 3 | Provider contract, conversations, runtime, streaming chat | Real chat with own agent; history persists |
| 4 | Upload, async processing, embeddings, retrieval in runtime | Grounded answers with sources; isolation and deletion tests pass |
| 5 | Memory controls, tool registry, one tool, approvals | Controllable memory; one tool end-to-end; approvals enforced |
| 6 | Usage ledger, activity history, observability, CI, security review | Controlled beta is supportable |

## Post-MVP (do not pull forward without a reason)

- **Phase 7** — OAuth integrations, webhooks, scheduled jobs.
- **Phase 8** — Visual workflows and multi-agent coordination.
- **Phase 9** — Local desktop companion (secure outbound connection, sandboxed capabilities).
- **Phase 10** — Marketplace, public API, billing, enterprise controls.
