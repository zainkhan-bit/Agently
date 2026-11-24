import Link from "next/link";

import { PageHeading } from "@/components/PageHeading";

import { agentsPath } from "./paths";

export function AgentMissing({ workspaceId }: { workspaceId: string }) {
  return (
    <div className="flex flex-col gap-4">
      <PageHeading title="Agent not found">Agent not found</PageHeading>
      <p>It does not exist in this workspace.</p>
      <Link href={agentsPath(workspaceId)} className="self-start underline">
        My Agents
      </Link>
    </div>
  );
}
