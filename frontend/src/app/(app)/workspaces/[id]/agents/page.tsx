import type { Metadata } from "next";

import { AgentList } from "@/features/agents/AgentList";

export const metadata: Metadata = { title: "My Agents" };

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ view?: string | string[] }>;
};

export default async function AgentsPage({ params, searchParams }: Props) {
  const { id } = await params;
  const archived = (await searchParams).view === "archived";
  return <AgentList key={`${id} ${archived}`} workspaceId={id} archived={archived} />;
}
