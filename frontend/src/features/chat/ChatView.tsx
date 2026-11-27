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

/**
 * The message being answered, until the answer is complete, refused, stopped or failed. Its text
 * is shown as it arrives; nothing here is HTML.
 */
type Pending = {
  requestId: string;
  content: string;
  phase: "sending" | "generating" | "stopping";
  text: string;
  /** Whether the server has the message: then it is in the list, and only the answer is missing. */
  stored: boolean;
};

/** How the last answer ended. Shown until the next message is sent. */
type Outcome = { text: string; alert: boolean };

const STATUS: Record<Pending["phase"], string> = {
  sending: "Sending…",
  generating: "The agent is answering…",
  stopping: "Stopping…",
};
const STOPPED = "Stopped. No answer was saved.";

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
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [moreError, setMoreError] = useState<string | null>(null);
  // From sending until what happened is shown: nothing else may be sent meanwhile.
  const busy = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const answering = useRef<string | null>(null);
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

  /**
   * Tells the server too: a proxy may keep the connection open after the browser closed it.
   * Only the answer to this message is stopped; the server replies once it has ended.
   */
  const stopOnServer = useCallback(
    (requestId: string, keepalive = false) =>
      fetch(`/api${path}/messages/stop`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }),
        keepalive,
      }).catch(() => undefined),
    [path],
  );

  // Leaving the page stops the answer: the server then saves none.
  useEffect(
    () => () => {
      if (!controller.current || !answering.current) return;
      controller.current.abort();
      void stopOnServer(answering.current, true);
    },
    [stopOnServer],
  );

  /** The newest messages, without hiding the ones shown meanwhile. Null if they could not be read. */
  const refreshLatest = useCallback(async (): Promise<ChatMessage[] | null> => {
    try {
      const { data } = await apiFetch<MessagePage>(`${path}/messages`, { cache: "no-store" });
      setHistory((now) =>
        now.kind === "ready" ? { ...now, messages: merge(now.messages, data.items) } : now,
      );
      return data.items;
    } catch {
      return null;
    }
  }, [path]);

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
  const running = pending !== null;
  const available = builder === "available" && disclosure !== null;
  const canSend = agent.status === "active" && available;
  const repeatable = pending === null ? unanswered(messages) : null;

  /** What the server says that may change what can be done next. */
  function react(error: ApiError) {
    if (error.code === "disclosure_changed") void loadBuilder();
    if (error.code === "agent_paused" || error.code === "agent_archived") void refreshAgent();
  }

  /**
   * After a stop or a failure, show what the server actually kept rather than guess: the
   * answer may have been saved, or the message may not have been.
   */
  async function showWhatWasKept(requestId: string, content: string, ended: Outcome) {
    const latest = await refreshLatest();
    setPending(null);
    busy.current = false;
    answering.current = null;
    if (latest === null) {
      setOutcome({ ...ended, text: `${ended.text} Reload the page to see what was saved.` });
      return;
    }
    const question = latest.find((message) => message.request_id === requestId);
    const answered = question && latest.some((m) => m.sequence === question.sequence + 1);
    if (answered) {
      setOutcome({ text: "The answer was saved after all.", alert: false });
    } else if (question) {
      setOutcome(ended);
    } else {
      setDraft((now) => now || content);
      setOutcome({ ...ended, text: `${ended.text} Your message was not saved: it is back below.` });
    }
  }

  /** ``stored``: whether the server may already have this message, as for every retry. */
  async function send(requestId: string, content: string, stored: boolean) {
    if (busy.current || disclosure === null) return;
    busy.current = true;
    answering.current = requestId;
    const abort = new AbortController();
    controller.current = abort;
    setOutcome(null);
    setPending({ requestId, content, phase: "sending", text: "", stored });
    let answered = false;
    let failure: string | null = null;
    let refused: ApiError | null = null;
    try {
      await streamMessage(
        `${path}/messages/stream?disclosure=${disclosure}`,
        { request_id: requestId, content },
        abort.signal,
        (event) => {
          if (event.type === "message") {
            add([event.message]);
            setPending((now) =>
              now && now.requestId === requestId ? { ...now, phase: "generating", stored: true } : now,
            );
          } else if (event.type === "piece") {
            setPending((now) =>
              now && now.requestId === requestId ? { ...now, text: now.text + event.text } : now,
            );
          } else if (event.type === "done") {
            add([event.answer.message, event.answer.answer]);
            answered = true;
          } else {
            failure = event.message;
          }
        },
      );
    } catch (error) {
      if (abort.signal.aborted) {
        // Stopped: stopAnswer shows the outcome once the server has stopped too.
      } else if (error instanceof ApiError && error.status === 401) {
        router.replace("/login");
      } else if (error instanceof ApiError && error.status < 500 && !stored) {
        refused = error;
      } else {
        failure =
          error instanceof StreamBrokenError || error instanceof NetworkError
            ? new StreamBrokenError().message
            : errorMessage(error);
        if (error instanceof ApiError) react(error);
      }
    } finally {
      controller.current = null;
    }
    if (abort.signal.aborted) return;
    if (answered || refused || failure === null) {
      setPending(null);
      busy.current = false;
      answering.current = null;
    }
    if (answered) {
      setOutcome({ text: "Answer complete.", alert: false });
    } else if (refused) {
      // A new message refused before anything was stored: the text goes back where it was typed.
      setDraft((now) => now || content);
      setOutcome({ text: errorMessage(refused), alert: false });
      react(refused);
      if (refused.status === 404) void load();
      composer.current?.focus();
    } else if (failure !== null) {
      await showWhatWasKept(requestId, content, { text: failure, alert: true });
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const content = draft;
    if (!canSend || busy.current || content.trim() === "") return;
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

  /** Retry stays unavailable until the server has stopped: it would stop the retry too. */
  async function stopAnswer() {
    if (!pending || pending.phase === "stopping") return;
    const { requestId, content } = pending;
    setPending({ ...pending, phase: "stopping" });
    controller.current?.abort();
    await stopOnServer(requestId);
    await showWhatWasKept(requestId, content, { text: STOPPED, alert: false });
  }

  /** Only a message the server has: one it does not have went back to the box. */
  function retry() {
    if (repeatable?.request_id) void send(repeatable.request_id, repeatable.content, true);
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
      setOutcome({ text: errorMessage(error), alert: false });
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
            <li className="flex flex-col gap-1" aria-busy="true">
              <span className="font-semibold">{agent.name}</span>
              {pending.text && <p className={textClass}>{pending.text}</p>}
              {!pending.text && <p>…</p>}
            </li>
          )}
        </ol>
      )}
      <p role="status" aria-live="polite">
        {pending ? STATUS[pending.phase] : outcome && !outcome.alert ? outcome.text : ""}
      </p>
      {!pending && outcome?.alert && <p role="alert">{outcome.text}</p>}
      <div className="flex flex-wrap gap-2">
        {running && (
          <button
            type="button"
            onClick={() => void stopAnswer()}
            aria-disabled={pending.phase === "stopping"}
            className={buttonClass}
          >
            Stop answering
          </button>
        )}
        {repeatable && canSend && (
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
          aria-disabled={running || draft.trim() === ""}
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
