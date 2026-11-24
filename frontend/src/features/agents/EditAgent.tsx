"use client";

import Link from "next/link";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ApiError, apiSend } from "@/lib/api";
import { clearUnsaved, confirmLeave } from "@/lib/unsavedChanges";
import { usePageRouter } from "@/lib/usePageRouter";

import { AgentForm, type AgentFields } from "./AgentForm";
import { AgentMissing } from "./AgentMissing";
import { agentPath } from "./paths";
import type { Agent } from "./types";
import { useAgent } from "./useAgent";

export function EditAgent({ workspaceId, agentId }: { workspaceId: string; agentId: string }) {
  const router = usePageRouter();
  const { state, load } = useAgent(workspaceId, agentId);

  if (state.kind === "loading") return <p role="status">Loading agent…</p>;
  if (state.kind === "workspace missing") return <WorkspaceMissing />;
  if (state.kind === "missing") return <AgentMissing workspaceId={workspaceId} />;
  if (state.kind === "error") return <ErrorRetry message={state.message} onRetry={load} />;

  const { agent } = state;
  const path = agentPath(workspaceId, agent.id);

  async function save(values: AgentFields) {
    await apiSend<Agent>("PATCH", path, { version: agent.version, ...values });
    clearUnsaved();
    document.getElementById("content")?.focus();
    router.replace(path);
  }

  function loadLatest() {
    if (!confirmLeave()) return;
    clearUnsaved();
    document.getElementById("content")?.focus();
    load();
  }

  function errorHelp(error: unknown) {
    if (!(error instanceof ApiError) || error.code !== "version_conflict") return null;
    return (
      <>
        <a href={path} target="_blank" rel="noopener" className="self-start underline">
          Open the latest version (new tab)
        </a>
        <button type="button" onClick={loadLatest} className={buttonClass}>
          Discard my text and load the latest
        </button>
      </>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeading
        title={`Edit agent: ${agent.name}`}
        className="break-words whitespace-pre-wrap"
      >
        Edit {agent.name}
      </PageHeading>
      {agent.status === "archived" ? (
        <>
          <p>An archived agent cannot be edited. Restore it first.</p>
          <Link href={path} className="self-start underline">
            Back to the agent
          </Link>
        </>
      ) : (
        <AgentForm
          initial={{
            name: agent.name,
            purpose: agent.purpose ?? "",
            description: agent.description ?? "",
            instructions: agent.instructions,
          }}
          submitLabel="Save changes"
          cancelHref={path}
          checkHint="open the agent in a new tab to see."
          onSave={save}
          errorHelp={errorHelp}
        />
      )}
    </div>
  );
}
