# AI Runtime

How a message becomes an answer (Slice 3.3). Code: `backend/app/modules/runtime/`. No tools, knowledge or memory yet.

## Lifecycle

1. **Access:** session, membership, agent, conversation. Only the conversation's creator gets this far (404 otherwise).
2. **Rate limit:** 60 messages per person and 200 per workspace and hour, repeats included. Counted after the access check.
3. **Refused before anything is stored:** an outdated data notice, no provider, invalid text, no free slot (8 calls at once per process), a paused or archived agent, an answer already being made in this conversation, a full conversation, a prompt over the token budget.
4. **First transaction:** stores the person's message and a `running` execution with the agent's current version. Then nothing is locked and no database connection is held.
5. **Model call:** through the configured provider with its spending limits (`provider_spend`), `PROVIDER_TIMEOUT_SECONDS` and an output limit of 4,000 tokens. The server never retries.
6. **Second transaction:** checks everything again, and stores the answer with its version and the result together. If the conversation, agent or membership is gone, nothing is stored.

Closing a run before it ends cancels it: no answer is stored, the record says `cancelled`.

## Streaming and stopping (Slice 3.4)

`POST .../messages/stream` sends server-sent events: `message` (the stored message), `piece` (text, in order), then `done` (both stored messages) or `error` (a fixed code and text). Refusals before the call are ordinary error responses. Responses are `private, no-store, no-transform`, so no proxy compresses and holds back the pieces.

`POST .../messages/stop` marks the running answer `cancelled` (code `stopped`). A running answer checks about once a second whether it was stopped, then closes the model call; its answer is never stored. Closing the connection is not enough on its own: the Next.js proxy keeps the connection to the backend open for 25 to 40 seconds after the browser closed it, so the page calls stop as well, also when it is left.

## Prompt

`prompt.py`; an exact snapshot is in `backend/tests/snapshots/runtime_prompt.txt`.

- **System message:** fixed rules, then the agent's name, purpose and instructions from one version. Nothing a person typed in chat.
- **User messages:** escaped inside `<user_message>` tags that they cannot close.
- **History:** whole answered exchanges of this conversation only, newest first, at most 20 messages and within the budget (32,000 estimated tokens). Unanswered messages are left out and take no room. So is what was typed under another data notice than the one in force.

Delimiters and roles reduce prompt injection, they do not make it impossible. An agent has no tools, so a misled answer can only be misleading text. How a real model resists is untested (BLOCKED).

## Repeats

The client gives each message a random `request_id`. The same id again in the same conversation:

| State | Result |
|---|---|
| Answered | The stored answer, without a call; only the rate limit can refuse it |
| Being answered | 409 `answer_in_progress` |
| Failed, still the last message | A new attempt; the message is not stored again |
| Failed, newer messages exist | 409 `retry_outdated` |
| Different text | 409 `request_reused` |

A run that its server never finished blocks its conversation for the provider timeout plus 60 seconds. The next accepted message then records it as `abandoned`, and an answer that still arrives is dropped. Until then its record says `running`.

If the database is too busy to store an answer, the person gets `answer_not_saved`; the record keeps the tokens, and the message can be repeated.

## Records

`executions` has one row per attempt: status (`running`, `succeeded`, `failed`, `cancelled`, `timed_out`), version, model, duration, tokens when known, and a code from our own errors. It holds no text. The database allows `succeeded` only with a stored answer, one running attempt per conversation, and one success per message. Rows go with their conversation; `provider_spend` stays.

## Privacy

Messages, instructions, answers and provider errors are never logged. Only known error classes reach people, with fixed messages. With Gemini, messages and instructions go to Google; the request must name the notice the person saw.
