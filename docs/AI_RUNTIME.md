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

`POST .../messages/stop` with `{"request_id": ...}` stops the answer to that one message, and to no other. It only records a request (`stop_requested_at`); the status stays `running` until the run has ended its model call and recorded `cancelled` (code `stopped`) itself. So the conversation stays busy, and the call keeps its slot, until the call has really ended. Stop then returns, or after at most 5 seconds; the page reloads the messages to show what was kept.

The model call runs on its own thread. The run checks about once a second whether it was stopped, also while the model sends nothing, and then sets the call's `cancel` event: providers end a `next()` that is waiting for the model within about a second (Gemini checks every 0.25 s). A call that will not end keeps its slot and gives it back itself when it does. An answer that arrives complete after a stop is not stored either, and is reported as stopped.

Closing the connection cancels the answer too, also when it closes before the first event was read: the response closes the run however it ends. That is not enough on its own: the Next.js proxy keeps the connection to the backend open for 25 to 40 seconds after the browser closed it, so the page calls stop as well, also when it is left.

After a stop or a failure the page reloads the newest messages and says what the server kept: the answer (it was saved after all), the message without an answer (Retry is offered), or nothing (the text goes back into the box). A new message can be sent at once. A retry is always treated as a message the server may already have.

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
