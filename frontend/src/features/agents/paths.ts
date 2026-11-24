/** The same paths in the app and, under /api, on the server. */
export const agentsPath = (workspaceId: string) =>
  `/workspaces/${encodeURIComponent(workspaceId)}/agents`;

export const agentPath = (workspaceId: string, agentId: string) =>
  `${agentsPath(workspaceId)}/${encodeURIComponent(agentId)}`;
