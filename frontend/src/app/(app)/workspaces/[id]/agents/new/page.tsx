import type { Metadata } from "next";

import { NewAgent } from "@/features/agents/NewAgent";

export const metadata: Metadata = { title: "New agent" };

export default async function NewAgentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <NewAgent key={id} workspaceId={id} />;
}
