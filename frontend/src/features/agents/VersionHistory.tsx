"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { focusContentOnFollow } from "@/lib/focusContent";
import { usePageRouter } from "@/lib/usePageRouter";

import { AgentMissing } from "./AgentMissing";
import { agentPath, versionPath, versionsPath } from "./paths";
import type { VersionPage, VersionSummary } from "./types";
import { useAgent } from "./useAgent";
import { SavedBy } from "./SavedBy";

type State =
  | { kind: "loading" }
  | { kind: "ready"; versions: VersionSummary[]; nextBefore: number | null }
  | { kind: "missing" }
  | { kind: "error"; message: string };

function changes({ changed, restored_from }: VersionSummary): string {
  if (changed === null) return "Created";
  const fields = `Changed: ${changed.join(", ")}`;
  return restored_from === null ? fields : `Restored from version ${restored_from}. ${fields}`;
}

export function VersionHistory({ workspaceId, agentId }: { workspaceId: string; agentId: string }) {
  const router = usePageRouter();
  const { state: agentState, load: loadAgent } = useAgent(workspaceId, agentId);
  const path = versionsPath(workspaceId, agentId);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [moreError, setMoreError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const { data } = await apiFetch<VersionPage>(path, { cache: "no-store" });
      setState({ kind: "ready", versions: data.items, nextBefore: data.next_before });
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 401) router.replace("/login");
      else if (status === 404 || status === 422) setState({ kind: "missing" });
      else setState({ kind: "error", message: errorMessage(error) });
    }
  }, [path, router]);

  useEffect(() => {
    void load();
  }, [load]);

  function retry() {
    loadAgent();
    void load();
  }

  if (agentState.kind === "workspace missing") return <WorkspaceMissing />;
  if (agentState.kind === "missing" || state.kind === "missing") {
    return <AgentMissing workspaceId={workspaceId} />;
  }
  if (agentState.kind === "error") return <ErrorRetry message={agentState.message} onRetry={retry} />;
  if (state.kind === "error") return <ErrorRetry message={state.message} onRetry={retry} />;
  if (agentState.kind === "loading" || state.kind === "loading") {
    return <p role="status">Loading versions…</p>;
  }
  const { agent } = agentState;
  const { versions, nextBefore } = state;

  async function showOlder() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setMoreError(null);
    try {
      const { data } = await apiFetch<VersionPage>(`${path}?before=${nextBefore}`, {
        cache: "no-store",
      });
      // This button is about to go away: keep focus on the page, not lost.
      if (data.next_before === null) document.getElementById("content")?.focus();
      setState({
        kind: "ready",
        versions: [...versions, ...data.items],
        nextBefore: data.next_before,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) router.replace("/login");
      else setMoreError(errorMessage(error));
    }
    inFlight.current = false;
    setPending(false);
  }

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={agentPath(workspaceId, agentId)}
        onClick={focusContentOnFollow}
        className="max-w-full self-start break-words whitespace-pre-wrap underline"
      >
        Back to {agent.name}
      </Link>
      <PageHeading
        title={`Version history: ${agent.name}`}
        className="break-words whitespace-pre-wrap"
      >
        Version history of {agent.name}
      </PageHeading>
      <ol reversed className="flex flex-col gap-4">
        {versions.map((version) => (
          <li key={version.id} className="rounded-md border border-current p-4 break-words">
            <Link
              href={versionPath(workspaceId, agentId, version.id)}
              onClick={focusContentOnFollow}
              className="font-semibold underline"
            >
              Version {version.number}
            </Link>
            {version.is_current && <strong> (current)</strong>}
            <p className="whitespace-pre-wrap">{version.name}</p>
            <p>{changes(version)}</p>
            <SavedBy version={version} />
          </li>
        ))}
      </ol>
      {moreError && <p role="alert">{moreError}</p>}
      {nextBefore !== null && (
        <button
          type="button"
          aria-disabled={pending}
          onClick={() => void showOlder()}
          className={buttonClass}
        >
          {pending ? "Loading…" : "Show older versions"}
        </button>
      )}
    </div>
  );
}
