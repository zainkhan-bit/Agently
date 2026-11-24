"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { Fragment, type KeyboardEvent, type MouseEvent, useCallback, useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { brand } from "@/config/brand";
import type { User } from "@/features/auth/types";
import type { Workspace } from "@/features/workspaces/types";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { writeLastWorkspace } from "@/lib/lastWorkspace";
import { confirmLeave } from "@/lib/unsavedChanges";

import { Sidebar } from "./Sidebar";

type State =
  | { kind: "loading" }
  | { kind: "ready"; user: User; workspaces: Workspace[] }
  | { kind: "error"; message: string };

/** The layout of every signed-in page. Pages load their own data, which the API authorises. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  // The API accepts ids in any case and returns them in lower case.
  const id = useParams<{ id?: string }>().id?.toLowerCase();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const main = useRef<HTMLElement>(null);
  const latest = useRef(0);

  const load = useCallback(async () => {
    const request = ++latest.current;
    const [me, list] = await Promise.allSettled([
      apiFetch<User>("/auth/me", { cache: "no-store" }),
      apiFetch<Workspace[]>("/workspaces", { cache: "no-store" }),
    ]);
    if (request !== latest.current) return;
    if (me.status === "fulfilled" && list.status === "fulfilled") {
      setState({ kind: "ready", user: me.value.data, workspaces: list.value.data });
      return;
    }
    const reasons = [me, list].flatMap((result) =>
      result.status === "rejected" ? [result.reason as unknown] : [],
    );
    if (reasons.some((reason) => reason instanceof ApiError && reason.status === 401)) {
      // Declining keeps the typed text on screen, so that it can be copied.
      if (confirmLeave()) router.replace("/login");
      return;
    }
    // A failed refresh keeps what is shown, unless somebody else is signed in now.
    const userId = me.status === "fulfilled" ? me.value.data.id : null;
    setState((now) =>
      now.kind === "ready" && (userId === null || userId === now.user.id)
        ? now
        : { kind: "error", message: errorMessage(reasons[0]) },
    );
  }, [router]);

  // Again on every navigation, so creates, deletes and another tab's sign-in show up.
  useEffect(() => {
    void load();
    return () => {
      latest.current += 1; // ignore the answer once the person has moved on
    };
  }, [load, pathname]);

  // Coming back to this tab, or to a page the browser kept after it was left (Back after sign out).
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === "visible") void load();
    }
    function onPageShow(event: PageTransitionEvent) {
      if (!event.persisted) return;
      setState({ kind: "loading" });
      void load();
    }
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [load]);

  const userId = state.kind === "ready" ? state.user.id : null;
  const inList = state.kind === "ready" && state.workspaces.some((item) => item.id === id);
  useEffect(() => {
    if (userId && id && inList) writeLastWorkspace(userId, id);
  }, [userId, id, inList]);

  // Focus would otherwise be lost with the link inside the closing menu.
  function onNavigate(event: MouseEvent) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; // new tab
    setMenuOpen(false);
    main.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key !== "Escape" || !menuOpen) return;
    setMenuOpen(false);
    menuButton.current?.focus();
  }

  if (state.kind !== "ready") {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-16">
        {state.kind === "loading" ? (
          <p role="status">Loading…</p>
        ) : (
          <ErrorRetry
            message={state.message}
            onRetry={() => {
              setState({ kind: "loading" });
              void load();
            }}
          />
        )}
      </main>
    );
  }
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]">
      <a
        href="#content"
        className="bg-background sr-only underline focus:not-sr-only focus:absolute focus:z-10 focus:p-2"
      >
        Skip to content
      </a>
      <header className="border-current max-lg:border-b lg:border-r" onKeyDown={onKeyDown}>
        <div className="flex items-center justify-between gap-4 p-4">
          <Link href="/" className="text-lg font-bold">
            {brand.name}
          </Link>
          <button
            ref={menuButton}
            type="button"
            aria-expanded={menuOpen}
            aria-controls="sidebar"
            onClick={() => setMenuOpen(!menuOpen)}
            className={`${buttonClass} lg:hidden`}
          >
            Menu
          </button>
        </div>
        <div id="sidebar" className={menuOpen ? undefined : "max-lg:hidden"}>
          <Sidebar
            user={state.user}
            workspaces={state.workspaces}
            routeId={id}
            pathname={pathname}
            onNavigate={onNavigate}
          />
        </div>
      </header>
      <main
        id="content"
        ref={main}
        tabIndex={-1}
        className="mx-auto w-full max-w-3xl min-w-0 px-4 py-8 outline-none"
      >
        {/* Another account never sees pages loaded for the previous one. */}
        <Fragment key={state.user.id}>{children}</Fragment>
      </main>
    </div>
  );
}
