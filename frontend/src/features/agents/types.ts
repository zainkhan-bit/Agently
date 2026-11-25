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

type VersionBase = {
  id: string;
  number: number;
  name: string;
  restored_from: number | null;
  /** Email. Null when they are not a member of the workspace now. */
  saved_by: string | null;
  created_at: string;
};

/** `changed` names the fields that differ from the version before; null for the first. */
export type VersionSummary = VersionBase & { is_current: boolean; changed: string[] | null };

export type Version = VersionBase & {
  purpose: string | null;
  description: string | null;
  instructions: string;
};

export type VersionPage = { items: VersionSummary[]; next_before: number | null };

export const STATUS_LABEL: Record<AgentStatus, string> = {
  active: "Active",
  paused: "Paused",
  archived: "Archived",
};
