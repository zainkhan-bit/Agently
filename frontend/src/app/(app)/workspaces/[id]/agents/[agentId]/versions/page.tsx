import type { Metadata } from "next";

import { VersionHistory } from "@/features/agents/VersionHistory";

export const metadata: Metadata = { title: "Version history" };

type Props = { params: Promise<{ id: string; agentId: string }> };

export default async function VersionsPage({ params }: Props) {
  const { id, agentId } = await params;
  return <VersionHistory key={`${id} ${agentId}`} workspaceId={id} agentId={agentId} />;
}
