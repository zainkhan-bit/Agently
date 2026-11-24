"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { usePageRouter } from "@/lib/usePageRouter";

import { SignOutButton } from "./SignOutButton";
import type { User } from "./types";

type State =
  | { kind: "loading" }
  | { kind: "signedIn"; email: string }
  | { kind: "error"; message: string };

export function AccountView() {
  const router = usePageRouter();
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const { data } = await apiFetch<User>("/auth/me", { cache: "no-store" });
      setState({ kind: "signedIn", email: data.email });
    } catch (error) {
      // Only a 401 means signed out. Anything else must not look like it.
      if (error instanceof ApiError && error.status === 401) router.replace("/login");
      else setState({ kind: "error", message: errorMessage(error) });
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.kind === "loading") return <p role="status">Checking your session…</p>;
  if (state.kind === "error") {
    return <ErrorRetry message={state.message} onRetry={() => void load()} />;
  }
  return (
    <div className="flex flex-col gap-4">
      <PageHeading>Account</PageHeading>
      <p className="break-words">Signed in as {state.email}</p>
      <SignOutButton />
    </div>
  );
}
