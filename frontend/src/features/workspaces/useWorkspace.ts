import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { usePageRouter } from "@/lib/usePageRouter";

import type { Member, Workspace } from "./types";

type State =
  | { kind: "loading" }
  | { kind: "ready"; workspace: Workspace; members: Member[] }
  | { kind: "missing" }
  | { kind: "error"; message: string };

/** One workspace and its members, read from the API, which checks membership. */
export function useWorkspace(id: string) {
  const router = usePageRouter();
  const path = `/workspaces/${encodeURIComponent(id)}`;
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const [workspace, members] = await Promise.all([
        apiFetch<Workspace>(path, { cache: "no-store" }),
        apiFetch<Member[]>(`${path}/members`, { cache: "no-store" }),
      ]);
      setState({ kind: "ready", workspace: workspace.data, members: members.data });
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 401) router.replace("/login");
      // 422 is a malformed id: to the person it is simply not a workspace.
      else if (status === 404 || status === 422) setState({ kind: "missing" });
      else setState({ kind: "error", message: errorMessage(error) });
    }
  }, [path, router]);

  useEffect(() => {
    void load();
  }, [load]);

  return { path, state, load };
}
