"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiFetch, apiPost, errorMessage, fieldErrors } from "@/lib/api";

import type { Workspace } from "./types";

type State =
  | { kind: "loading" }
  | { kind: "ready"; workspaces: Workspace[] }
  | { kind: "error"; message: string };

const BUTTON = "self-start rounded-md border border-current px-3 py-2 font-medium disabled:opacity-60";

export function WorkspaceList() {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [nameError, setNameError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const { data } = await apiFetch<Workspace[]>("/workspaces", { cache: "no-store" });
      setState({ kind: "ready", workspaces: data });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) router.replace("/login");
      else setState({ kind: "error", message: errorMessage(error) });
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    const name = new FormData(event.currentTarget).get("name");
    setPending(true);
    setNameError(null);
    try {
      const { data } = await apiPost<Workspace>("/workspaces", { name });
      router.push(`/workspaces/${data.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) router.replace("/login");
      setNameError(fieldErrors(error).name ?? errorMessage(error));
      inFlight.current = false;
      setPending(false);
    }
  }

  if (state.kind === "loading") return <p>Loading workspaces…</p>;
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
  const empty = state.workspaces.length === 0;
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">Workspaces</h1>
      {empty ? (
        <p>You have no workspaces yet. Create your first workspace.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {state.workspaces.map((workspace) => (
            <li key={workspace.id} className="break-words">
              <Link href={`/workspaces/${workspace.id}`} className="underline">
                {workspace.name}
              </Link>{" "}
              ({workspace.role})
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={create} noValidate className="flex flex-col gap-4">
        <label className="flex flex-col gap-1">
          New workspace name
          <input
            name="name"
            autoComplete="off"
            aria-invalid={Boolean(nameError)}
            aria-describedby={nameError ? "name-error" : undefined}
            className="rounded-md border border-current px-3 py-2"
          />
        </label>
        {nameError && (
          <p id="name-error" role="alert">
            {nameError}
          </p>
        )}
        <button type="submit" disabled={pending} className={BUTTON}>
          {pending ? "Creating…" : "Create workspace"}
        </button>
      </form>
    </div>
  );
}
