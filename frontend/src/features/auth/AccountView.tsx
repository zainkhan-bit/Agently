"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch, apiPost, errorMessage } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "signedIn"; email: string }
  | { kind: "error"; message: string };

const BUTTON = "self-start rounded-md border border-current px-3 py-2 font-medium";

export function AccountView() {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const { data } = await apiFetch<{ email: string }>("/auth/me", { cache: "no-store" });
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

  async function signOut() {
    setPending(true);
    setSignOutError(null);
    try {
      await apiPost("/auth/logout");
      router.replace("/login");
    } catch {
      setSignOutError("Could not confirm sign out. You may still be signed in. Please try again.");
      setPending(false);
    }
  }

  if (state.kind === "loading") return <p>Checking your session…</p>;
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
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Account</h1>
      <p className="break-words">Signed in as {state.email}</p>
      {signOutError && <p role="alert">{signOutError}</p>}
      <button
        type="button"
        disabled={pending}
        onClick={() => void signOut()}
        className={`${BUTTON} disabled:opacity-60`}
      >
        Sign out
      </button>
    </div>
  );
}
