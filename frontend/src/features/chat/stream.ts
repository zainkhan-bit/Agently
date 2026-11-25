import { ApiError, NetworkError } from "@/lib/api";

import type { Answer, ChatMessage } from "./types";

export type StreamEvent =
  | { type: "message"; message: ChatMessage }
  | { type: "piece"; text: string }
  | { type: "done"; answer: Answer }
  | { type: "error"; code: string; message: string };

/** Thrown when the connection broke: the answer may or may not have been stored. */
export class StreamBrokenError extends Error {
  constructor() {
    super("The connection was lost. The answer may have been saved: retry to see it.");
    this.name = "StreamBrokenError";
  }
}

/** Split server-sent events. Returns the complete events and what is left over. */
export function parseEvents(buffer: string): { events: StreamEvent[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: StreamEvent[] = [];
  for (const block of blocks) {
    let name = "";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) name = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    const value: unknown = JSON.parse(data);
    if (name === "message") events.push({ type: "message", message: value as ChatMessage });
    else if (name === "piece") events.push({ type: "piece", text: (value as { text: string }).text });
    else if (name === "done") events.push({ type: "done", answer: value as Answer });
    else if (name === "error") {
      const { code, message } = value as { code: string; message: string };
      events.push({ type: "error", code, message });
    }
  }
  return { events, rest };
}

/**
 * Send a message and hand over its events as they arrive. Refusals before anything was stored
 * throw ApiError; an unreachable server throws NetworkError; a broken stream StreamBrokenError.
 * Aborting the signal cancels the answer on the server.
 */
export async function streamMessage(
  path: string,
  body: { request_id: string; content: string },
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new NetworkError();
  }
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    const error = (parsed as { error?: { code?: unknown; message?: unknown } } | null)?.error;
    if (typeof error?.code === "string" && typeof error.message === "string") {
      throw new ApiError(response.status, error.code, error.message);
    }
    if (response.status >= 500) throw new StreamBrokenError();
    throw new ApiError(response.status, "unknown_error", "Request failed.");
  }
  if (!response.body) throw new StreamBrokenError();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseEvents(buffer);
      buffer = rest;
      for (const event of events) {
        if (event.type === "done" || event.type === "error") finished = true;
        onEvent(event);
      }
    }
  } catch (error) {
    if (signal.aborted) throw error;
    throw new StreamBrokenError();
  }
  if (!finished) throw new StreamBrokenError();
}
