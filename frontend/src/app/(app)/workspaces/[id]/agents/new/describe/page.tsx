import type { Metadata } from "next";

import { DescribeAgent } from "@/features/agents/DescribeAgent";

export const metadata: Metadata = { title: "Describe your agent" };

export default async function DescribeAgentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DescribeAgent key={id} workspaceId={id} />;
}
