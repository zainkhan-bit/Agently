# Product Vision — Agently

> Working name and tagline. Branding lives in one place in code (`brand` config) so it can be renamed later.

**Tagline:** "Build Your Own AI. Put It to Work."

## Purpose

Agently is a multi-tenant SaaS platform where individuals and organisations create their own AI agents, give them instructions and private knowledge, choose a model, enable approved tools, and use those agents to get work done from one organised workspace.

**Product statement (MVP):** A user can create a personal AI agent, configure its behaviour, give it private knowledge, chat with it, and safely use a small set of approved capabilities from one organised workspace.

## Users

One flexible product for:

- **Individuals / professionals** — priority for early usability testing.
- **Developers** — priority for early usability testing.
- **Small businesses** — supported by workspaces with owner/member roles.

We do not build separate products per audience.

## Long-term vision (not the MVP)

An AI workforce operating system: prompt-based and advanced agent creation, multiple model providers and user-supplied keys, agent memory and knowledge, a reusable tool/skill registry, integrations (Google, Microsoft, GitHub, Slack, Telegram, Notion, webhooks), scheduled/background execution, a secure local desktop companion, multi-agent teams, templates, a marketplace, public APIs, and enterprise controls.

## MVP boundary

**In:** auth and sessions; workspaces with strict isolation; owner/member roles; dashboard; agent CRUD, duplicate, pause/archive; prompt-to-agent and manual configuration; one real model provider behind an abstraction; streaming chat with history; knowledge upload, processing, embeddings, retrieval; user-controlled memory; a small tool registry with approvals; execution history and usage tracking; limits and guardrails; tests, CI, docs.

**Out (post-MVP):** local desktop agent, arbitrary shell execution, visual workflow editor, multi-agent orchestration, public marketplace/sharing, large integration catalogue, model training, enterprise SSO/SCIM/compliance, production billing.

See [MASTER_PRD.md](MASTER_PRD.md) for requirements and acceptance criteria and [ROADMAP.md](ROADMAP.md) for phases.
