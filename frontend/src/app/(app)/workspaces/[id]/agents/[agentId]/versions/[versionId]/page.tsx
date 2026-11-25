import type { Metadata } from "next";

import { VersionView } from "@/features/agents/VersionView";

export const metadata: Metadata = { title: "Version" };

type Props = { params: Promise<{ id: string; agentId: string; versionId: string }> };

export default async function VersionPage({ params }: Props) {
  const { id, agentId, versionId } = await params;
  return (
    <VersionView
      key={`${id} ${agentId} ${versionId}`}
      workspaceId={id}
      agentId={agentId}
      versionId={versionId}
    />
  );
}
