# ADR-0006: Gemini as the first real provider, and the spending limit

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

`docs/MASTER_PRD.md` Q1 named Anthropic as the first real adapter. The owner has a Google Gemini key on the free tier.

## Decision

1. **Gemini is the first real adapter**, over REST with httpx and no SDK. The key is only ever in the `x-goog-api-key` header.
2. **One model per server, from an allowed list** in `app/modules/providers/models.py`: `gemini-3.5-flash-lite` (default) and `gemini-3.8-flash`. Agents do not choose a model yet.
3. **The tier is declared** in `GEMINI_TIER`, because a key does not reveal it. It defaults to free, and production refuses free: Google uses what the free tier receives and people may read it.
4. **Every real call is reserved at its worst-case cost** against rolling limits for the whole server ($1 per 24 hours, $10 per 30 days, configurable). Success corrects it to the real cost. It is given back when nothing was sent (no free worker, no time left, no connection) or Google answered 401, 402, 403, 404 or 429. Anything else keeps it. The owner decided this on 2026-11-26 after the review: before, failures that cost nothing could block drafts for a day. That those statuses are free is our inference, not a documented Google promise.
5. **People are told before they type.** The page sends the notice it showed, and the server refuses answers given under another one.

## Alternatives considered

- Google's SDK: its own logging and retries.
- `?key=` in the URL: URLs reach proxy logs and error messages.
- A limit on calls: breaks when models, prices or message lengths change.
- Refunding all failed calls: Google may have charged for them.
- Refunding none: about 60 failures a day would block everyone.
- Socket timeouts alone: they bound each read, so a trickle of bytes never ends.

## Consequences

- The limit is as accurate as Google's token counts and our price list. Read the pricing page again when changing a model.
- Failures can use up the day early. If the database cannot record a call, none is made.
- **Before any deployment:** the paid tier; a monthly spend cap in AI Studio (it can lag by about 10 minutes); nobody under 18 (Google's terms); users in the EEA, the UK and Switzerland require the paid tier.
- `provider_spend` is not the usage ledger of ADR-0005. It names no person or workspace.
