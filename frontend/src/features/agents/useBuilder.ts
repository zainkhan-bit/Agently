import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

import { type Disclosure, isDisclosure } from "./disclosure";
import { builderPath } from "./paths";

/** "closed": the form was open, and drafts stopped being available or the notice is unknown. */
type Builder = "loading" | "available" | "unavailable" | "unknown" | "closed";

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
    const next: Builder =
      known === null ? "unknown" : data.available ? "available" : "unavailable";
    return { known, next };
  }, [workspaceId]);

  /** Asks again while the form is open. Never takes the form, and the answers in it, away. */
  const refresh = useCallback(async () => {
    const { known, next } = await ask();
    if (next === "available" && known !== null) setDisclosure(known);
    setBuilder(next === "available" ? "available" : "closed");
  }, [ask]);

  const load = useCallback(async () => {
    setBuilder("loading");
    try {
      const { known, next } = await ask();
      setDisclosure(known);
      setBuilder(next);
    } catch {
      setBuilder("unknown");
    }
  }, [ask]);

  useEffect(() => {
    void load();
  }, [load]);

  return { builder, disclosure, load, refresh };
}
