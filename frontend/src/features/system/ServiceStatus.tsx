"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type Readiness = {
  status: "ready" | "not_ready";
  checks: { database: "ok" | "not_configured" | "unavailable" };
};

type State =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "degraded"; message: string }
  | { kind: "offline"; message: string };

const DATABASE_MESSAGES: Record<Readiness["checks"]["database"], string> = {
  ok: "Database connected.",
  not_configured: "The database is not configured. Set DATABASE_URL in backend/.env (see README).",
  unavailable: "The database is not reachable. Make sure PostgreSQL is running.",
};

export function ServiceStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const check = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const { data } = await apiFetch<Readiness>("/health/ready", { acceptStatuses: [503] });
      if (data?.status === "ready") {
        setState({ kind: "ready" });
      } else {
        const db = data?.checks?.database ?? "unavailable";
        setState({ kind: "degraded", message: DATABASE_MESSAGES[db] ?? DATABASE_MESSAGES.unavailable });
      }
    } catch {
      setState({
        kind: "offline",
        message: "The Agently API is not reachable. Start the backend server (see README).",
      });
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  return (
    <section
      aria-labelledby="service-status-heading"
      aria-live="polite"
      className="rounded-xl border border-black/10 p-4 dark:border-white/15"
    >
      <h2 id="service-status-heading" className="text-sm font-semibold">
        System status
      </h2>
      {state.kind === "loading" && <p className="mt-2 text-sm">Checking services…</p>}
      {state.kind === "ready" && (
        <p className="mt-2 text-sm">
          <span aria-hidden="true">● </span>All services are ready.
        </p>
      )}
      {(state.kind === "degraded" || state.kind === "offline") && (
        <div className="mt-2 text-sm">
          <p role="alert">
            <span aria-hidden="true">▲ </span>
            {state.kind === "degraded" ? "Service degraded: " : "Service unavailable: "}
            {state.message}
          </p>
          <button
            type="button"
            onClick={() => void check()}
            className="mt-3 rounded-md border border-current px-3 py-1.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            Retry
          </button>
        </div>
      )}
    </section>
  );
}
