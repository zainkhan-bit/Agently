import type { Metadata } from "next";

import { EditAgent } from "@/features/agents/EditAgent";

export const metadata: Metadata = { title: "Edit agent" };

type Props = { params: Promise<{ id: string; agentId: string }> };

export default async function EditAgentPage({ params }: Props) {
  const { id, agentId } = await params;
  return <EditAgent key={`${id} ${agentId}`} workspaceId={id} agentId={agentId} />;
}
