import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

import { builderPath } from "./paths";

type Builder = "loading" | "available" | "unavailable" | "unknown";

/** Whether this server can generate drafts. */
export function useBuilder(workspaceId: string) {
  const [builder, setBuilder] = useState<Builder>("loading");

  const load = useCallback(async () => {
    setBuilder("loading");
    try {
      const { data } = await apiFetch<{ available: boolean }>(builderPath(workspaceId), {
        cache: "no-store",
      });
      setBuilder(data.available ? "available" : "unavailable");
    } catch {
      setBuilder("unknown");
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  return { builder, load };
}
