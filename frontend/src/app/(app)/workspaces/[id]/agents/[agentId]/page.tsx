import type { Metadata } from "next";

import { AgentView } from "@/features/agents/AgentView";

export const metadata: Metadata = { title: "Agent" };

type Props = { params: Promise<{ id: string; agentId: string }> };

export default async function AgentPage({ params }: Props) {
  const { id, agentId } = await params;
  return <AgentView key={`${id} ${agentId}`} workspaceId={id} agentId={agentId} />;
}
