"use client";

import Link from "next/link";
import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { AgentMissing } from "@/features/agents/AgentMissing";
import { noticeText } from "@/features/agents/disclosure";
import { chatPath, chatsPath } from "@/features/agents/paths";
import { useAgent } from "@/features/agents/useAgent";
import { useBuilder } from "@/features/agents/useBuilder";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ApiError, apiFetch, errorMessage, NetworkError } from "@/lib/api";
import { usePageRouter } from "@/lib/usePageRouter";

import { StreamBrokenError, streamMessage } from "./stream";
import { formatTime } from "./time";
import type { ChatMessage, MessagePage } from "./types";

const MAX_CHARACTERS = 8_000;
const textClass = "break-words whitespace-pre-wrap";

type History =
  | { kind: "loading" }
  | { kind: "ready"; messages: ChatMessage[]; nextBefore: number | null }
  | { kind: "missing" }
  | { kind: "error"; message: string };

/** The message being answered. Its text is shown as it arrives; nothing here is HTML. */
type Pending = {
  requestId: string;
  content: string;
  phase: "sending" | "generating" | "failed" | "stopped";
  text: string;
  error: string;
  /** Whether the server has the message: then it is in the list, and only the answer is missing. */
  stored: boolean;
};

const STATUS: Record<Pending["phase"], string> = {
  sending: "Sending…",
  generating: "The agent is answering…",
  failed: "No answer.",
  stopped: "Stopped. No answer was saved.",
};

function merge(messages: ChatMessage[], added: ChatMessage[]): ChatMessage[] {
  const byId = new Map(messages.map((message) => [message.id, message]));
  for (const message of added) byId.set(message.id, message);
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence);
}

/** What could make the last message worth repeating: it was the person's, and is unanswered. */
function unanswered(messages: ChatMessage[]): ChatMessage | null {
  const last = messages.at(-1);
  return last?.role === "user" && last.request_id ? last : null;
}

type Props = { workspaceId: string; agentId: string; conversationId: string };

export function ChatView({ workspaceId, agentId, conversationId }: Props) {
  const router = usePageRouter();
  const { state: agentState, load: loadAgent, refresh: refreshAgent } = useAgent(
    workspaceId,
    agentId,
  );
  const { builder, disclosure, load: loadBuilder } = useBuilder(workspaceId);
  const path = chatPath(workspaceId, agentId, conversationId);
  const [history, setHistory] = useState<History>({ kind: "loading" });
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState("");
  const [moreError, setMoreError] = useState<string | null>(null);
  const busy = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    setHistory({ kind: "loading" });
    try {
      const { data } = await apiFetch<MessagePage>(`${path}/messages`, { cache: "no-store" });
      setHistory({ kind: "ready", messages: data.items, nextBefore: data.next_before });
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 401) router.replace("/login");
      else if (status === 404 || status === 422) setHistory({ kind: "missing" });
      else setHistory({ kind: "error", message: errorMessage(error) });
    }
  }, [path, router]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Tells the server too: a proxy may keep the connection open after the browser closed it. */
  const stopOnServer = useCallback(
    (keepalive = false) =>
      fetch(`/api${path}/messages/stop`, {
        method: "POST",
        credentials: "same-origin",
        keepalive,
      }).catch(() => undefined),
    [path],
  );

  // Leaving the page stops the answer: the server then saves none.
  useEffect(
    () => () => {
      if (!controller.current) return;
      controller.current.abort();
      void stopOnServer(true);
    },
    [stopOnServer],
  );

  const add = useCallback((messages: ChatMessage[]) => {
    setHistory((now) =>
      now.kind === "ready" ? { ...now, messages: merge(now.messages, messages) } : now,
    );
  }, []);

  if (agentState.kind === "loading" || history.kind === "loading") {
    return <p role="status">Loading conversation…</p>;
  }
  if (agentState.kind === "workspace missing") return <WorkspaceMissing />;
  if (agentState.kind === "missing") return <AgentMissing workspaceId={workspaceId} />;
  if (agentState.kind === "error") {
    return <ErrorRetry message={agentState.message} onRetry={loadAgent} />;
  }
  if (history.kind === "missing") return <ConversationMissing {...{ workspaceId, agentId }} />;
  if (history.kind === "error") {
    return <ErrorRetry message={history.message} onRetry={() => void load()} />;
  }

  const { agent } = agentState;
  const messages = history.messages;
  const running = pending?.phase === "sending" || pending?.phase === "generating";
  const available = builder === "available" && disclosure !== null;
  const canSend = agent.status === "active" && available;
  const repeatable = pending === null ? unanswered(messages) : null;

  async function send(requestId: string, content: string, stored: boolean) {
    if (busy.current || disclosure === null) return;
    busy.current = true;
    const abort = new AbortController();
    controller.current = abort;
    setNotice("");
    setPending({ requestId, content, phase: "sending", text: "", error: "", stored });
    const update = (change: Partial<Pending>) =>
      setPending((now) => (now && now.requestId === requestId ? { ...now, ...change } : now));
    let refused = false;
    try {
      await streamMessage(
        `${path}/messages/stream?disclosure=${disclosure}`,
        { request_id: requestId, content },
        abort.signal,
        (event) => {
          if (event.type === "message") {
            add([event.message]);
            update({ phase: "generating", stored: true });
          } else if (event.type === "piece") {
            setPending((now) =>
              now && now.requestId === requestId ? { ...now, text: now.text + event.text } : now,
            );
          } else if (event.type === "done") {
            add([event.answer.message, event.answer.answer]);
            setPending(null);
            setNotice("Answer complete.");
          } else {
            update({ phase: "failed", error: event.message });
          }
        },
      );
    } catch (error) {
      if (abort.signal.aborted) {
        update({ phase: "stopped" });
      } else if (error instanceof ApiError && error.status === 401) {
        router.replace("/login");
      } else if (error instanceof ApiError && error.status < 500 && !stored) {
        // Refused before anything was stored: the text goes back where it was typed.
        refused = true;
        setPending(null);
        setDraft((now) => now || content);
        setNotice(errorMessage(error));
        if (error.code === "disclosure_changed") void loadBuilder();
        if (error.code === "agent_paused" || error.code === "agent_archived") {
          void refreshAgent();
        }
        if (error.status === 404) void load();
      } else {
        const text =
          error instanceof StreamBrokenError || error instanceof NetworkError
            ? new StreamBrokenError().message
            : errorMessage(error);
        update({ phase: "failed", error: text });
        if (error instanceof ApiError && error.code === "answer_in_progress") void load();
      }
    } finally {
      busy.current = false;
      controller.current = null;
      if (refused) composer.current?.focus();
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const content = draft;
    if (!canSend || busy.current || pending || content.trim() === "") return;
    setDraft("");
    void send(crypto.randomUUID(), content, false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter starts a new line, as in most chats.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  async function stopAnswer() {
    controller.current?.abort();
    await stopOnServer();
  }

  function retry() {
    if (pending) void send(pending.requestId, pending.content, pending.stored);
    else if (repeatable?.request_id) void send(repeatable.request_id, repeatable.content, true);
  }

  async function loadEarlier() {
    if (history.kind !== "ready" || history.nextBefore === null) return;
    setMoreError(null);
    try {
      const { data } = await apiFetch<MessagePage>(
        `${path}/messages?before=${history.nextBefore}`,
        { cache: "no-store" },
      );
      setHistory((now) =>
        now.kind === "ready"
          ? { ...now, messages: merge(now.messages, data.items), nextBefore: data.next_before }
          : now,
      );
    } catch (error) {
      setMoreError(errorMessage(error));
    }
  }

  async function remove() {
    if (running || !window.confirm("Delete this conversation permanently?")) return;
    try {
      await apiFetch(path, { method: "DELETE" });
      document.getElementById("content")?.focus();
      router.replace(chatsPath(workspaceId, agentId));
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link href={chatsPath(workspaceId, agentId)} className="self-start underline">
        All conversations with {agent.name}
      </Link>
      <PageHeading title={`Chat with ${agent.name}`} className={textClass}>
        Chat with {agent.name}
      </PageHeading>
      {agent.status !== "active" && (
        <p role="note" className="font-semibold">
          This agent is {agent.status}. It cannot answer until it is{" "}
          {agent.status === "paused" ? "resumed" : "restored and resumed"}.
        </p>
      )}
      {builder === "unavailable" && (
        <p role="note">Chat is not available: no AI provider is set up on this server.</p>
      )}
      {builder === "unknown" && (
        <p role="note">
          Chat is not available right now.{" "}
          <button type="button" onClick={() => void loadBuilder()} className="underline">
            Check again
          </button>
        </p>
      )}
      {history.nextBefore !== null && (
        <button type="button" onClick={() => void loadEarlier()} className={buttonClass}>
          Show earlier messages
        </button>
      )}
      {moreError && <p role="alert">{moreError}</p>}
      {messages.length === 0 && !pending ? (
        <p>No messages yet. Write the first one below.</p>
      ) : (
        <ol aria-label="Conversation" className="flex flex-col gap-4">
          {messages.map((message) => (
            <MessageItem key={message.id} message={message} agentName={agent.name} />
          ))}
          {pending && !pending.stored && (
            <li className="flex flex-col gap-1">
              <span className="font-semibold">You</span>
              <p className={textClass}>{pending.content}</p>
            </li>
          )}
          {pending && pending.phase !== "sending" && (
            <li className="flex flex-col gap-1" aria-busy={pending.phase === "generating"}>
              <span className="font-semibold">{agent.name}</span>
              {pending.text && <p className={textClass}>{pending.text}</p>}
              {pending.text && !running && <p className="text-sm">Incomplete, not saved.</p>}
              {pending.phase === "generating" && !pending.text && <p>…</p>}
            </li>
          )}
        </ol>
      )}
      <p role="status" aria-live="polite">
        {pending ? STATUS[pending.phase] : notice}
      </p>
      {pending?.phase === "failed" && <p role="alert">{pending.error}</p>}
      <div className="flex flex-wrap gap-2">
        {running && (
          <button type="button" onClick={() => void stopAnswer()} className={buttonClass}>
            Stop answering
          </button>
        )}
        {((pending && !running) || repeatable) && canSend && (
          <button type="button" onClick={retry} className={buttonClass}>
            Retry the last message
          </button>
        )}
      </div>
      <form onSubmit={submit} className="flex flex-col gap-2">
        <p role="note" id="chat-notice" aria-live="polite" className="font-semibold">
          {disclosure !== null ? noticeText(disclosure, "chat") : ""}
        </p>
        <label htmlFor="chat-message" className="font-medium">
          Message
        </label>
        <textarea
          id="chat-message"
          ref={composer}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          maxLength={MAX_CHARACTERS}
          rows={4}
          disabled={!canSend}
          aria-describedby="chat-notice chat-help"
          className="w-full rounded-md border border-current px-3 py-2"
        />
        <p id="chat-help" className="text-sm">
          Enter sends, Shift+Enter starts a new line. At most {MAX_CHARACTERS.toLocaleString()}{" "}
          characters.
        </p>
        <button
          type="submit"
          disabled={!canSend}
          aria-disabled={running || pending !== null || draft.trim() === ""}
          className={buttonClass}
        >
          Send
        </button>
      </form>
      <section aria-labelledby="delete-heading" className="flex flex-col gap-2">
        <h2 id="delete-heading" className="font-semibold">
          Delete conversation
        </h2>
        <button
          type="button"
          aria-disabled={running}
          onClick={() => void remove()}
          className={buttonClass}
        >
          Delete permanently
        </button>
      </section>
    </div>
  );
}

function MessageItem({ message, agentName }: { message: ChatMessage; agentName: string }) {
  const mine = message.role === "user";
  return (
    <li className="flex flex-col gap-1">
      <span className="font-semibold">
        {mine ? "You" : agentName}{" "}
        <span className="text-sm font-normal">
          {formatTime(message.created_at)}
          {!mine && message.agent_version !== null && ` · version ${message.agent_version}`}
        </span>
      </span>
      <p className={textClass}>{message.content}</p>
    </li>
  );
}

function ConversationMissing({ workspaceId, agentId }: { workspaceId: string; agentId: string }) {
  return (
    <div className="flex flex-col gap-4">
      <PageHeading>Conversation not found</PageHeading>
      <p>It does not exist, was deleted, or is not yours.</p>
      <Link href={chatsPath(workspaceId, agentId)} className="self-start underline">
        Your conversations with this agent
      </Link>
    </div>
  );
}
