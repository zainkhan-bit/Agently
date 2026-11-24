"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { usePageRouter } from "@/lib/usePageRouter";

import { agentPath, agentsPath } from "./paths";
import { type AgentPage, type AgentSummary, STATUS_LABEL } from "./types";

type State =
  | { kind: "loading" }
  | { kind: "ready"; agents: AgentSummary[]; total: number; offset: number }
  | { kind: "missing" }
  | { kind: "error"; message: string };

const PAGE_SIZE = 100;

export function AgentList({ workspaceId, archived }: { workspaceId: string; archived: boolean }) {
  const router = usePageRouter();
  const path = agentsPath(workspaceId);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [moreError, setMoreError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);

  const fetchPage = useCallback(
    async (offset: number) => {
      const query = `archived=${archived}&limit=${PAGE_SIZE}&offset=${offset}`;
      return (await apiFetch<AgentPage>(`${path}?${query}`, { cache: "no-store" })).data;
    },
    [path, archived],
  );

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const { items, total } = await fetchPage(0);
      setState({ kind: "ready", agents: items, total, offset: items.length });
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 401) router.replace("/login");
      else if (status === 404 || status === 422) setState({ kind: "missing" });
      else setState({ kind: "error", message: errorMessage(error) });
    }
  }, [fetchPage, router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.kind === "loading") return <p role="status">Loading agents…</p>;
  if (state.kind === "missing") return <WorkspaceMissing />;
  if (state.kind === "error") {
    return <ErrorRetry message={state.message} onRetry={() => void load()} />;
  }
  const { agents, total, offset } = state;

  async function showMore() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setMoreError(null);
    try {
      const page = await fetchPage(offset);
      // Agents created meanwhile push others onto the next page, so some may come twice.
      const known = new Set(agents.map(({ id }) => id));
      const next = offset + page.items.length;
      // This button is about to go away: keep focus on the page, not lost.
      if (next >= page.total || page.items.length === 0) {
        document.getElementById("content")?.focus();
      }
      setState({
        kind: "ready",
        agents: [...agents, ...page.items.filter(({ id }) => !known.has(id))],
        total: page.items.length === 0 ? next : page.total,
        offset: next,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) router.replace("/login");
      else setMoreError(errorMessage(error));
    }
    inFlight.current = false;
    setPending(false);
  }

  const views = [
    { label: "Current", href: path, isCurrent: !archived },
    { label: "Archived", href: `${path}?view=archived`, isCurrent: archived },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={archived ? "Archived agents" : "My Agents"}>
        {archived ? "Archived agents" : "My Agents"}
      </PageHeading>
      <Link href={`${path}/new`} className={buttonClass}>
        New agent
      </Link>
      <nav aria-label="Agent views">
        <ul className="flex gap-4">
          {views.map(({ label, href, isCurrent }) => (
            <li key={label}>
              <Link
                href={href}
                aria-current={isCurrent ? "page" : undefined}
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                  // The list is replaced: without this, focus would be lost with the link.
                  document.getElementById("content")?.focus();
                }}
                className={isCurrent ? "border-b-4 border-current font-semibold" : "underline"}
              >
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {agents.length === 0 ? (
        <p>
          {archived
            ? "No archived agents."
            : "No current agents in this workspace. Use New agent to create one."}
        </p>
      ) : (
        <ul className="flex flex-col gap-4">
          {agents.map((agent) => (
            <li key={agent.id} className="rounded-md border border-current p-4 break-words">
              <Link
                href={agentPath(workspaceId, agent.id)}
                className="font-semibold whitespace-pre-wrap underline"
              >
                {agent.name}
              </Link>
              <p>Status: {STATUS_LABEL[agent.status]}</p>
              {agent.purpose && <p className="whitespace-pre-wrap">{agent.purpose}</p>}
            </li>
          ))}
        </ul>
      )}
      {moreError && <p role="alert">{moreError}</p>}
      {offset < total && (
        <button
          type="button"
          aria-disabled={pending}
          onClick={() => void showMore()}
          className={buttonClass}
        >
          {pending ? "Loading…" : "Show more"}
        </button>
      )}
    </div>
  );
}
