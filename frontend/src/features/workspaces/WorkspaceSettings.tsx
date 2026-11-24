"use client";

import { useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { usePageRouter } from "@/lib/usePageRouter";

import { useWorkspace } from "./useWorkspace";
import { WorkspaceMissing } from "./WorkspaceMissing";

export function WorkspaceSettings({ id }: { id: string }) {
  const router = usePageRouter();
  const { path, state, load } = useWorkspace(id);
  const [typedName, setTypedName] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function remove() {
    setPending(true);
    setDeleteError(null);
    try {
      await apiFetch(path, { method: "DELETE" });
      router.replace("/dashboard");
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 401) router.replace("/login");
      else if (status === 404) router.replace(path); // already gone: not found there, and the layout refreshes
      else {
        setDeleteError(errorMessage(error));
        setPending(false);
      }
    }
  }

  if (state.kind === "loading") return <p role="status">Loading settings…</p>;
  if (state.kind === "missing") return <WorkspaceMissing />;
  if (state.kind === "error") {
    return <ErrorRetry message={state.message} onRetry={() => void load()} />;
  }
  const { workspace, members } = state;
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={`Settings: ${workspace.name}`}>Workspace settings</PageHeading>
      <p className="break-words whitespace-pre-wrap">{workspace.name}</p>
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
          <p>This permanently deletes the workspace and everyone&apos;s access to it. Accounts are kept. Type the workspace name to confirm.</p>
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
            className={buttonClass}
          >
            Delete permanently
          </button>
        </section>
      )}
    </div>
  );
}
