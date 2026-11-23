"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch, errorMessage } from "@/lib/api";

import type { Member, Workspace } from "./types";

type State =
  | { kind: "loading" }
  | { kind: "ready"; workspace: Workspace; members: Member[] }
  | { kind: "missing" }
  | { kind: "error"; message: string };

const BUTTON = "self-start rounded-md border border-current px-3 py-2 font-medium disabled:opacity-60";

export function WorkspaceView({ id }: { id: string }) {
  const router = useRouter();
  const path = `/workspaces/${encodeURIComponent(id)}`;
  const [state, setState] = useState<State>({ kind: "loading" });
  const [typedName, setTypedName] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

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

  async function remove() {
    setPending(true);
    setDeleteError(null);
    try {
      await apiFetch(path, { method: "DELETE" });
      router.replace("/workspaces");
    } catch (error) {
      setDeleteError(errorMessage(error));
      setPending(false);
    }
  }

  const back = (
    <Link href="/workspaces" className="underline">
      All workspaces
    </Link>
  );
  if (state.kind === "loading") return <p>Loading workspace…</p>;
  if (state.kind === "missing") {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">Workspace not found</h1>
        <p>It does not exist, or you are not a member.</p>
        {back}
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert">{state.message}</p>
        <button type="button" onClick={() => void load()} className={BUTTON}>
          Retry
        </button>
      </div>
    );
  }
  const { workspace, members } = state;
  return (
    <div className="flex flex-col gap-6">
      {back}
      <h1 className="text-2xl font-bold break-words whitespace-pre-wrap">{workspace.name}</h1>
      <p>Your role: {workspace.role}</p>
      <section aria-labelledby="members-heading">
        <h2 id="members-heading" className="font-semibold">
          Members
        </h2>
        <ul>
          {members.map((member) => (
            <li key={member.user_id} className="break-words">
              {member.email} ({member.role})
            </li>
          ))}
        </ul>
      </section>
      {workspace.role === "owner" && (
        <section aria-labelledby="delete-heading" className="flex flex-col gap-4">
          <h2 id="delete-heading" className="font-semibold">
            Delete workspace
          </h2>
          <p>This is permanent. Type the workspace name to confirm.</p>
          <label className="flex flex-col gap-1">
            Workspace name
            <input
              value={typedName}
              onChange={(event) => setTypedName(event.target.value)}
              autoComplete="off"
              className="rounded-md border border-current px-3 py-2"
            />
          </label>
          {deleteError && <p role="alert">{deleteError}</p>}
          <button
            type="button"
            disabled={pending || typedName !== workspace.name}
            onClick={() => void remove()}
            className={BUTTON}
          >
            Delete permanently
          </button>
        </section>
      )}
    </div>
  );
}
