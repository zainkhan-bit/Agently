/** Message text was written by a person or a model: render it as text only, never as HTML. */
export type ChatMessage = {
  id: string;
  sequence: number;
  role: "user" | "assistant";
  content: string;
  agent_version: number | null;
  /** Set for what the person sent: repeating it can never store it twice. */
  request_id: string | null;
  created_at: string;
};

export type MessagePage = { items: ChatMessage[]; next_before: number | null };

export type Conversation = {
  id: string;
  agent_id: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type ConversationPage = { items: Conversation[]; total: number };

export type Answer = { message: ChatMessage; answer: ChatMessage };
