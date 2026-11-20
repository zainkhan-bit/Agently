# ADR-0001: Provisional product decisions

- **Status:** Accepted (provisional)
- **Date:** 2026-11-20

## Context

No product documents beyond `AGENT_BUILD_GUIDE.md` exist. Section 1.5 of the guide lists commercial choices that are not final and must be recorded rather than repeatedly asked about.

## Decision

| Topic | Decision |
|---|---|
| Audience | One flexible product; early testing prioritises individuals/professionals and developers. |
| Model strategy | Architecture supports platform-managed keys and later user-supplied keys. First version implements only one provider path that can be tested with an available credential, plus a deterministic mock for tests. No key is fabricated or committed. |
| Execution | Cloud execution only for MVP. Local execution is post-MVP (Phase 9). |
| Brand | "Agently" / "Build Your Own AI. Put It to Work." — centralised in one config module per app. |
| Billing | Usage is tracked from the start; no paid billing or payment collection until a provider is configured and the owner authorises it. |
| Workspace on signup | A personal workspace is created automatically at registration so the MVP journey has no dead end. Additional workspaces can be created explicitly. |
| Not-found vs forbidden | Cross-tenant access returns 404 so resource existence is not leaked. |

## Consequences

These may change; any change gets a new ADR that supersedes the relevant row.
