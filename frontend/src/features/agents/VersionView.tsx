"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ApiError, apiFetch, apiPost, errorMessage } from "@/lib/api";
import { focusContentOnFollow } from "@/lib/focusContent";
import { usePageRouter } from "@/lib/usePageRouter";

import { AgentMissing } from "./AgentMissing";
import { changeFailure } from "./failure";
import { agentPath, versionPath, versionsPath } from "./paths";
import { SavedBy } from "./SavedBy";
import type { Agent, Version } from "./types";
import { useAgent } from "./useAgent";

type State =
  | { kind: "loading" }
  | { kind: "ready"; version: Version }
  | { kind: "missing" }
  | { kind: "error"; message: string };

type Props = { workspaceId: string; agentId: string; versionId: string };

const textClass = "break-words whitespace-pre-wrap";
const focusContent = () => document.getElementById("content")?.focus();

export function VersionView({ workspaceId, agentId, versionId }: Props) {
  const router = usePageRouter();
  const { state: agentState, load: loadAgent, refresh } = useAgent(workspaceId, agentId);
  const path = versionPath(workspaceId, agentId, versionId);
  const history = versionsPath(workspaceId, agentId);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [error, setError] = useState<{ text: string; offerLatest: boolean } | null>(null);
  const [done, setDone] = useState("");
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const { data } = await apiFetch<Version>(path, { cache: "no-store" });
      setState({ kind: "ready", version: data });
    } catch (failure) {
      const status = failure instanceof ApiError ? failure.status : 0;
      if (status === 401) router.replace("/login");
      else if (status === 404 || status === 422) setState({ kind: "missing" });
      else setState({ kind: "error", message: errorMessage(failure) });
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
  if (agentState.kind === "missing") return <AgentMissing workspaceId={workspaceId} />;
  if (agentState.kind === "error") return <ErrorRetry message={agentState.message} onRetry={retry} />;
  if (state.kind === "error") return <ErrorRetry message={state.message} onRetry={retry} />;
  if (agentState.kind === "loading" || state.kind === "loading") {
    return <p role="status">Loading version…</p>;
  }
  if (state.kind === "missing") {
    return (
      <div className="flex flex-col gap-4">
        <PageHeading title="Version not found">Version not found</PageHeading>
        <p>This agent has no such version.</p>
        <Link href={history} onClick={focusContentOnFollow} className="self-start underline">
          Version history
        </Link>
      </div>
    );
  }
  const { agent } = agentState;
  const { version } = state;

  async function rollBack() {
    if (inFlight.current) return;
    const question =
      `Roll back to version ${version.number}? This saves a copy of it as a new version ` +
      `and replaces the current configuration, name included. No version is lost.`;
    if (!window.confirm(question)) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    setDone("");
    try {
      const { data } = await apiPost<Agent>(`${path}/rollback`, { version: agent.version });
      if (data.version === agent.version) {
        setDone("Nothing changed: the current version already has this configuration.");
      } else {
        focusContent(); // so that the agent page's heading takes it
        router.push(agentPath(workspaceId, agentId));
      }
    } catch (failure) {
      const status = failure instanceof ApiError ? failure.status : 0;
      if (status === 401) {
        router.replace("/login");
        return;
      }
      const code = failure instanceof ApiError ? failure.code : "";
      const offerLatest = code === "version_conflict" || code === "busy";
      setError({
        text: changeFailure(failure, "open the version history to see."),
        offerLatest,
      });
      if (status === 404) {
        focusContent();
        await refresh();
      }
      // A stale page keeps its old version number until the person asks for the latest: their
      // next confirmation must not silently apply to something they have not seen.
      else if (status === 409 && !offerLatest) await refresh();
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  function loadLatest() {
    focusContent();
    setError(null);
    retry();
  }

  return (
    <div className="flex flex-col gap-6">
      <Link href={history} onClick={focusContentOnFollow} className="self-start underline">
        Version history
      </Link>
      <PageHeading title={`Version ${version.number}: ${agent.name}`} className={textClass}>
        Version {version.number} of {agent.name}
      </PageHeading>
      <div>
        <SavedBy version={version} />
        {version.restored_from !== null && <p>Restored from version {version.restored_from}.</p>}
      </div>
      <section aria-labelledby="configuration-heading" className="flex flex-col gap-4">
        <h2 id="configuration-heading" className="font-semibold">
          Configuration
        </h2>
        <dl className="flex flex-col gap-4">
          {(["name", "purpose", "description", "instructions"] as const).map((field) => (
            <div key={field}>
              <dt className="font-medium capitalize">{field}</dt>
              <dd className={textClass}>{version[field] ?? "Not set"}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section aria-labelledby="rollback-heading" className="flex flex-col gap-4">
        <h2 id="rollback-heading" className="font-semibold">
          Roll back
        </h2>
        {version.number === agent.version ? (
          <p>This is the current version.</p>
        ) : agent.status === "archived" ? (
          <p>An archived agent cannot be rolled back. Restore it first.</p>
        ) : (
          <>
            <p>The current version is {agent.version}. Rolling back keeps every version.</p>
            <button
              type="button"
              aria-disabled={pending}
              onClick={() => void rollBack()}
              className={buttonClass}
            >
              Roll back to version {version.number}
            </button>
          </>
        )}
        <p role="status">{pending ? "Working…" : done}</p>
        {error && <p role="alert">{error.text}</p>}
        {error?.offerLatest && (
          <button type="button" onClick={loadLatest} className={buttonClass}>
            Load the latest
          </button>
        )}
      </section>
    </div>
  );
}
