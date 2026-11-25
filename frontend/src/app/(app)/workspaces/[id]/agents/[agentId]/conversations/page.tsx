import type { Metadata } from "next";

import { ChatList } from "@/features/chat/ChatList";

export const metadata: Metadata = { title: "Conversations" };

type Props = { params: Promise<{ id: string; agentId: string }> };

export default async function ConversationsPage({ params }: Props) {
  const { id, agentId } = await params;
  return <ChatList key={`${id} ${agentId}`} workspaceId={id} agentId={agentId} />;
}
