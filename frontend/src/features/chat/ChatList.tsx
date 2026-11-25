"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { AgentMissing } from "@/features/agents/AgentMissing";
import { agentPath, chatPath, chatsPath } from "@/features/agents/paths";
import { useAgent } from "@/features/agents/useAgent";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ApiError, apiFetch, apiPost, errorMessage } from "@/lib/api";
import { focusContentOnFollow } from "@/lib/focusContent";
import { usePageRouter } from "@/lib/usePageRouter";

import { formatTime } from "./time";
import type { Conversation, ConversationPage } from "./types";

type List =
  | { kind: "loading" }
  | { kind: "ready"; items: Conversation[]; total: number }
  | { kind: "error"; message: string };

const textClass = "break-words whitespace-pre-wrap";

/** The person's own conversations with one agent. Nobody else's are ever listed. */
export function ChatList({ workspaceId, agentId }: { workspaceId: string; agentId: string }) {
  const router = usePageRouter();
  const { state: agentState, load: loadAgent } = useAgent(workspaceId, agentId);
  const [list, setList] = useState<List>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const path = chatsPath(workspaceId, agentId);

  const load = useCallback(async () => {
    setList({ kind: "loading" });
    try {
      const { data } = await apiFetch<ConversationPage>(`${path}?limit=100`, {
        cache: "no-store",
      });
      setList({ kind: "ready", items: data.items, total: data.total });
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) router.replace("/login");
      else setList({ kind: "error", message: errorMessage(failure) });
    }
  }, [path, router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (agentState.kind === "loading") return <p role="status">Loading conversations…</p>;
  if (agentState.kind === "workspace missing") return <WorkspaceMissing />;
  if (agentState.kind === "missing") return <AgentMissing workspaceId={workspaceId} />;
  if (agentState.kind === "error") {
    return <ErrorRetry message={agentState.message} onRetry={loadAgent} />;
  }
  if (list.kind === "error") return <ErrorRetry message={list.message} onRetry={() => void load()} />;

  const { agent } = agentState;
  const canStart = agent.status === "active";

  async function startConversation() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    try {
      const { data } = await apiPost<Conversation>(path);
      document.getElementById("content")?.focus(); // so that the new page's heading takes it
      router.push(chatPath(workspaceId, agentId, data.id));
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) router.replace("/login");
      else setError(errorMessage(failure));
      inFlight.current = false;
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link href={agentPath(workspaceId, agentId)} className="self-start underline">
        Back to {agent.name}
      </Link>
      <PageHeading title={`Conversations with ${agent.name}`} className={textClass}>
        Conversations with {agent.name}
      </PageHeading>
      <p>Only you can see your conversations. Other members and owners cannot.</p>
      {canStart ? (
        <button
          type="button"
          aria-disabled={pending}
          onClick={() => void startConversation()}
          className={buttonClass}
        >
          New conversation
        </button>
      ) : (
        <p role="note">
          This agent is {agent.status}, so no conversation can be started. Existing ones can still
          be read and deleted.
        </p>
      )}
      <p role="status">{pending ? "Starting…" : ""}</p>
      {error && <p role="alert">{error}</p>}
      {list.kind === "loading" ? (
        <p role="status">Loading conversations…</p>
      ) : list.items.length === 0 ? (
        <p>No conversations yet.</p>
      ) : (
        <ul aria-label="Your conversations" className="flex flex-col gap-2">
          {list.items.map((conversation) => (
            <li key={conversation.id}>
              <Link
                href={chatPath(workspaceId, agentId, conversation.id)}
                onClick={focusContentOnFollow}
                className="underline"
              >
                Conversation started {formatTime(conversation.created_at)}
              </Link>{" "}
              · {conversation.message_count}{" "}
              {conversation.message_count === 1 ? "message" : "messages"}, last activity{" "}
              {formatTime(conversation.updated_at)}
            </li>
          ))}
        </ul>
      )}
      {list.kind === "ready" && list.total > list.items.length && (
        <p>Showing the {list.items.length} most recent of {list.total} conversations.</p>
      )}
    </div>
  );
}
