import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

import { type Disclosure, isDisclosure } from "./disclosure";
import { builderPath } from "./paths";

type Builder = "loading" | "available" | "unavailable" | "unknown";

/** Whether this server can generate drafts, and who receives the answers. */
export function useBuilder(workspaceId: string) {
  const [builder, setBuilder] = useState<Builder>("loading");
  const [disclosure, setDisclosure] = useState<Disclosure | null>(null);

  const ask = useCallback(async () => {
    const { data } = await apiFetch<{ available: boolean; disclosure: unknown }>(
      builderPath(workspaceId),
      { cache: "no-store" },
    );
    const known = isDisclosure(data.disclosure) ? data.disclosure : null;
    setDisclosure(known);
    if (known === null) setBuilder("unknown");
    else setBuilder(data.available ? "available" : "unavailable");
  }, [workspaceId]);

  const load = useCallback(async () => {
    setBuilder("loading");
    try {
      await ask();
    } catch {
      setBuilder("unknown");
    }
  }, [ask]);

  useEffect(() => {
    void load();
  }, [load]);

  return { builder, disclosure, load, ask };
}
