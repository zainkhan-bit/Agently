"use client";

import { PageHeading } from "@/components/PageHeading";
import { useWorkspace } from "@/features/workspaces/useWorkspace";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ErrorRetry } from "@/components/ErrorRetry";
import { apiPost } from "@/lib/api";
import { clearUnsaved } from "@/lib/unsavedChanges";
import { usePageRouter } from "@/lib/usePageRouter";

import { AgentForm } from "./AgentForm";
import { agentPath, agentsPath } from "./paths";
import type { Agent } from "./types";

const EMPTY = { name: "", purpose: "", description: "", instructions: "" };

export function NewAgent({ workspaceId }: { workspaceId: string }) {
  const router = usePageRouter();
  // Nobody should fill in a form for a workspace they cannot use.
  const { state, load } = useWorkspace(workspaceId);

  if (state.kind === "loading") return <p role="status">Loading…</p>;
  if (state.kind === "missing") return <WorkspaceMissing />;
  if (state.kind === "error") {
    return <ErrorRetry message={state.message} onRetry={() => void load()} />;
  }
  const path = agentsPath(workspaceId);
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title="New agent">New agent</PageHeading>
      <AgentForm
        initial={EMPTY}
        submitLabel="Create agent"
        cancelHref={path}
        checkHint="look in My Agents before trying again."
        onSave={async (values) => {
          const { data } = await apiPost<Agent>(path, values);
          clearUnsaved();
          document.getElementById("content")?.focus();
          router.replace(agentPath(workspaceId, data.id));
        }}
      />
    </div>
  );
}
