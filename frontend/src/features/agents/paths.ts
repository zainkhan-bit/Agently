/** The same paths in the app and, under /api, on the server, except describe. */
export const agentsPath = (workspaceId: string) =>
  `/workspaces/${encodeURIComponent(workspaceId)}/agents`;

export const agentPath = (workspaceId: string, agentId: string) =>
  `${agentsPath(workspaceId)}/${encodeURIComponent(agentId)}`;

export const describePath = (workspaceId: string) => `${agentsPath(workspaceId)}/new/describe`;

/** On the server only. */
export const builderPath = (workspaceId: string) =>
  `/workspaces/${encodeURIComponent(workspaceId)}/agent-builder`;
