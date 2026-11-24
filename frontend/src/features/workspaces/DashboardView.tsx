"use client";

import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { AgentCount } from "@/features/agents/AgentCount";

import { useWorkspace } from "./useWorkspace";
import { WorkspaceMissing } from "./WorkspaceMissing";

const cardClass = "rounded-md border border-current p-4";

export function DashboardView({ id }: { id: string }) {
  const { state, load } = useWorkspace(id);

  if (state.kind === "loading") return <p role="status">Loading dashboard…</p>;
  if (state.kind === "missing") return <WorkspaceMissing />;
  if (state.kind === "error") {
    return <ErrorRetry message={state.message} onRetry={() => void load()} />;
  }
  const { workspace, members } = state;
  return (
    <div className="flex flex-col gap-6">
      <PageHeading
        title={`Dashboard: ${workspace.name}`}
        className="break-words whitespace-pre-wrap"
      >
        {workspace.name}
      </PageHeading>
      <dl className="grid gap-4 sm:grid-cols-2">
        <div className={cardClass}>
          <dt>Your role</dt>
          <dd className="text-2xl font-semibold capitalize">{workspace.role}</dd>
        </div>
        <div className={cardClass}>
          <dt>Members</dt>
          <dd className="text-2xl font-semibold">{members.length}</dd>
        </div>
      </dl>
      <section aria-labelledby="agents-heading" className={cardClass}>
        <h2 id="agents-heading" className="font-semibold">
          Agents
        </h2>
        <AgentCount workspaceId={id} />
      </section>
    </div>
  );
}
