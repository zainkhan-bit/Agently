"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorRetry } from "@/components/ErrorRetry";
import type { User } from "@/features/auth/types";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { pickWorkspace } from "@/lib/lastWorkspace";
import { usePageRouter } from "@/lib/usePageRouter";

import type { Workspace } from "./types";

/** Sends the signed-in person to their workspace, or to the create form if they have none. */
export function OpenDashboard() {
  const router = usePageRouter();
  const [error, setError] = useState<string | null>(null);

  const open = useCallback(async () => {
    setError(null);
    try {
      const [me, list] = await Promise.all([
        apiFetch<User>("/auth/me", { cache: "no-store" }),
        apiFetch<Workspace[]>("/workspaces", { cache: "no-store" }),
      ]);
      const workspace = pickWorkspace(me.data.id, list.data);
      router.replace(workspace ? `/workspaces/${workspace.id}` : "/workspaces");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) router.replace("/login");
      else setError(errorMessage(reason));
    }
  }, [router]);

  useEffect(() => {
    void open();
  }, [open]);

  if (error) return <ErrorRetry message={error} onRetry={() => void open()} />;
  return <p role="status">Opening your dashboard…</p>;
}
