"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ApiError, apiFetch, apiPost } from "@/lib/api";
import { focusContentOnFollow } from "@/lib/focusContent";
import { usePageRouter } from "@/lib/usePageRouter";

import { AgentMissing } from "./AgentMissing";
import { changeFailure } from "./failure";
import { agentPath, agentsPath, chatsPath, versionsPath } from "./paths";
import { type Agent, type AgentStatus, STATUS_LABEL } from "./types";
import { useAgent } from "./useAgent";

const STATUS_TEXT: Record<AgentStatus, string> = {
  active: "People can chat with it.",
  paused: "A paused agent cannot answer until it is resumed. Conversations with it are kept.",
  archived: "An archived agent cannot run or be edited. Restoring it makes it paused.",
};

type StatusAction = "pause" | "resume" | "archive" | "restore";
const ACTION_LABEL: Record<StatusAction, string> = {
  pause: "Pause",
  resume: "Resume",
  archive: "Archive",
  restore: "Restore",
};

const textClass = "break-words whitespace-pre-wrap";
const focusContent = () => document.getElementById("content")?.focus();

type Place = "actions" | "delete";

export function AgentView({ workspaceId, agentId }: { workspaceId: string; agentId: string }) {
  const router = usePageRouter();
  const { state, load, refresh, setAgent } = useAgent(workspaceId, agentId);
  const [typedName, setTypedName] = useState("");
  const [error, setError] = useState<{ text: string; place: Place } | null>(null);
  const [done, setDone] = useState("");
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);

  if (state.kind === "loading") return <p role="status">Loading agent…</p>;
  if (state.kind === "workspace missing") return <WorkspaceMissing />;
  if (state.kind === "missing") return <AgentMissing workspaceId={workspaceId} />;
  if (state.kind === "error") return <ErrorRetry message={state.message} onRetry={load} />;

  const { agent, role } = state;
  const path = agentPath(workspaceId, agent.id);

  async function change(place: Place, check: string, request: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    setDone("");
    try {
      await request();
    } catch (failure) {
      const status = failure instanceof ApiError ? failure.status : 0;
      if (status === 401) {
        router.replace("/login");
        return;
      }
      setError({ text: changeFailure(failure, check), place });
      // What is shown is out of date: gone, changed by someone else, or the role was lost.
      if (status === 404) focusContent();
      if (status === 404 || status === 409 || status === 403) await refresh();
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  const changeStatus = (action: StatusAction) =>
    change("actions", "reload the page to see.", async () => {
      const { data } = await apiPost<Agent>(`${path}/${action}`);
      setAgent(data);
      setDone(`Saved. The agent is now ${data.status}.`);
    });

  const duplicate = () =>
    change("actions", "look in My Agents before trying again.", async () => {
      const { data } = await apiPost<Agent>(`${path}/duplicate`);
      focusContent(); // so that the new page's heading takes it
      router.push(agentPath(workspaceId, data.id));
    });

  const remove = () =>
    change("delete", "reload the page to see.", async () => {
      await apiFetch(path, { method: "DELETE" });
      focusContent();
      router.replace(agentsPath(workspaceId));
    });

  const archived = agent.status === "archived";
  const canDelete = role === "owner";
  // The key keeps the button, and the focus on it, when its action changes.
  const statusButton = (key: string, action: StatusAction) => (
    <button
      key={key}
      type="button"
      aria-disabled={pending}
      onClick={() => void changeStatus(action)}
      className={buttonClass}
    >
      {ACTION_LABEL[action]}
    </button>
  );
  return (
    <div className="flex flex-col gap-6">
      <Link href={agentsPath(workspaceId)} className="self-start underline">
        All agents
      </Link>
      <PageHeading title={`Agent: ${agent.name}`} className={textClass}>
        {agent.name}
      </PageHeading>
      <p>
        <strong>Status: {STATUS_LABEL[agent.status]}.</strong> {STATUS_TEXT[agent.status]}
      </p>
      <Link
        href={chatsPath(workspaceId, agent.id)}
        onClick={focusContentOnFollow}
        className={buttonClass}
      >
        Chat with this agent
      </Link>
      <section aria-labelledby="actions-heading" className="flex flex-col gap-4">
        <h2 id="actions-heading" className="font-semibold">
          Actions
        </h2>
        <div className="flex flex-wrap gap-2">
          {!archived && (
            <Link key="edit" href={`${path}/edit`} className={buttonClass}>
              Edit
            </Link>
          )}
          <button
            key="duplicate"
            type="button"
            aria-disabled={pending}
            onClick={() => void duplicate()}
            className={buttonClass}
          >
            Duplicate
          </button>
          {!archived && statusButton("run", agent.status === "active" ? "pause" : "resume")}
          {statusButton("archive", archived ? "restore" : "archive")}
        </div>
        <p role="status">{pending ? "Working…" : done}</p>
        {error?.place === "actions" && <p role="alert">{error.text}</p>}
      </section>
      <section aria-labelledby="configuration-heading" className="flex flex-col gap-4">
        <h2 id="configuration-heading" className="font-semibold">
          Configuration
        </h2>
        <p>
          Version {agent.version}.{" "}
          <Link
            href={versionsPath(workspaceId, agent.id)}
            onClick={focusContentOnFollow}
            className="underline"
          >
            Version history
          </Link>
        </p>
        <dl className="flex flex-col gap-4">
          {(["purpose", "description", "instructions"] as const).map((field) => (
            <div key={field}>
              <dt className="font-medium capitalize">{field}</dt>
              <dd className={textClass}>{agent[field] ?? "Not set"}</dd>
            </div>
          ))}
        </dl>
      </section>
      {canDelete && (
        <section aria-labelledby="delete-heading" className="flex flex-col gap-4">
          <h2 id="delete-heading" className="font-semibold">
            Delete agent
          </h2>
          <p>
            This permanently deletes the agent, every saved version of its configuration, and
            everyone&apos;s conversations with it. Conversations are private: you cannot see what
            you would delete. Type the agent name to confirm.
          </p>
          <label className="flex flex-col gap-1">
            Agent name
            <input
              value={typedName}
              onChange={(event) => setTypedName(event.target.value)}
              autoComplete="off"
              className="rounded-md border border-current px-3 py-2"
            />
          </label>
          <button
            type="button"
            disabled={typedName !== agent.name}
            aria-disabled={pending}
            onClick={() => void remove()}
            className={buttonClass}
          >
            Delete permanently
          </button>
        </section>
      )}
      {error?.place === "delete" && <p role="alert">{error.text}</p>}
    </div>
  );
}
