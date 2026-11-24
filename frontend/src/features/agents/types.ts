export type AgentStatus = "active" | "paused" | "archived";

/** Text fields were written by people: render them as text only, never as HTML. */
export type AgentSummary = {
  id: string;
  status: AgentStatus;
  version: number;
  name: string;
  purpose: string | null;
  description: string | null;
};

export type Agent = AgentSummary & { instructions: string };

export type AgentPage = { items: AgentSummary[]; total: number };

export const STATUS_LABEL: Record<AgentStatus, string> = {
  active: "Active",
  paused: "Paused",
  archived: "Archived",
};
