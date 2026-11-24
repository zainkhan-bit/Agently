// The workspace a person last opened in this browser. Only a convenience for where sign-in lands:
// the server checks membership on every request. A shared browser keeps this after sign-out, so
// it holds one workspace id under the user's id and nothing readable.

const key = (userId: string) => `agently:last-workspace:${userId}`;

export function readLastWorkspace(userId: string): string | null {
  try {
    return localStorage.getItem(key(userId));
  } catch {
    return null; // storage is blocked or unavailable
  }
}

export function writeLastWorkspace(userId: string, workspaceId: string): void {
  try {
    localStorage.setItem(key(userId), workspaceId);
  } catch {
    // Storage is blocked, unavailable or full: the next sign-in opens the first workspace.
  }
}

/** The last-used workspace if it is still in the list, otherwise the first, otherwise none. */
export function pickWorkspace<T extends { id: string }>(
  userId: string,
  workspaces: T[],
): T | undefined {
  const last = readLastWorkspace(userId);
  return workspaces.find(({ id }) => id === last) ?? workspaces[0];
}
