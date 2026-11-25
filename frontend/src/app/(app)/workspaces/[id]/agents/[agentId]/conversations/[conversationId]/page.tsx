import type { Metadata } from "next";

import { ChatView } from "@/features/chat/ChatView";

export const metadata: Metadata = { title: "Chat" };

type Props = { params: Promise<{ id: string; agentId: string; conversationId: string }> };

export default async function ChatPage({ params }: Props) {
  const { id, agentId, conversationId } = await params;
  return (
    <ChatView
      key={`${id} ${agentId} ${conversationId}`}
      workspaceId={id}
      agentId={agentId}
      conversationId={conversationId}
    />
  );
}
