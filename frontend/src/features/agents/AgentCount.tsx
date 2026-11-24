"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { apiFetch, errorMessage } from "@/lib/api";

import { agentsPath } from "./paths";
import type { AgentPage } from "./types";

/** How many agents the workspace has. Its failure leaves the rest of the dashboard alone. */
export function AgentCount({ workspaceId }: { workspaceId: string }) {
  const path = agentsPath(workspaceId);
  const [total, setTotal] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await apiFetch<AgentPage>(`${path}?limit=1`, { cache: "no-store" });
      setTotal(data.total);
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="flex flex-col gap-2">
      {error !== null ? (
        <>
          <p role="alert">The number of agents could not be loaded. {error}</p>
          <button
            type="button"
            onClick={() => {
              // This button goes away while loading: keep focus on the page, not lost.
              document.getElementById("content")?.focus();
              void load();
            }}
            className={buttonClass}
          >
            Retry
          </button>
        </>
      ) : (
        <p>
          {total === null
            ? "Loading agents…"
            : `${total} current ${total === 1 ? "agent" : "agents"}, archived not counted.`}
        </p>
      )}
      <Link href={path} className="self-start underline">
        Open My Agents
      </Link>
    </div>
  );
}
