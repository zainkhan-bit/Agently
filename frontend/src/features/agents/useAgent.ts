import { useCallback, useEffect, useState } from "react";

import type { Role, Workspace } from "@/features/workspaces/types";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { usePageRouter } from "@/lib/usePageRouter";

import { agentPath } from "./paths";
import type { Agent } from "./types";

type State =
  | { kind: "loading" }
  | { kind: "ready"; agent: Agent; role: Role }
  | { kind: "missing" }
  | { kind: "workspace missing" }
  | { kind: "error"; message: string };

const isMissing = (reason: unknown) =>
  // 422 is a malformed id: to the person it simply does not exist.
  reason instanceof ApiError && (reason.status === 404 || reason.status === 422);

/** One agent and the person's role in its workspace, both checked by the API. */
export function useAgent(workspaceId: string, agentId: string) {
  const router = usePageRouter();
  const [state, setState] = useState<State>({ kind: "loading" });

  /** Read again while showing what is there. */
  const refresh = useCallback(async () => {
    const [workspace, agent] = await Promise.allSettled([
      apiFetch<Workspace>(`/workspaces/${encodeURIComponent(workspaceId)}`, { cache: "no-store" }),
      apiFetch<Agent>(agentPath(workspaceId, agentId), { cache: "no-store" }),
    ]);
    if (workspace.status === "fulfilled" && agent.status === "fulfilled") {
      setState({ kind: "ready", agent: agent.value.data, role: workspace.value.data.role });
      return;
    }
    const reasons = [workspace, agent].flatMap((result) =>
      result.status === "rejected" ? [result.reason as unknown] : [],
    );
    if (reasons.some((reason) => reason instanceof ApiError && reason.status === 401)) {
      router.replace("/login");
    } else if (workspace.status === "rejected" && isMissing(workspace.reason)) {
      setState({ kind: "workspace missing" });
    } else if (agent.status === "rejected" && isMissing(agent.reason)) {
      setState({ kind: "missing" });
    } else {
      setState({ kind: "error", message: errorMessage(reasons[0]) });
    }
  }, [workspaceId, agentId, router]);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    void refresh();
  }, [refresh]);

  const setAgent = useCallback((agent: Agent) => {
    setState((now) => (now.kind === "ready" ? { ...now, agent } : now));
  }, []);

  useEffect(load, [load]);

  return { state, load, refresh, setAgent };
}
