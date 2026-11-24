import { useEffect, useRef } from "react";

const MESSAGE = "You have unsaved changes. Leave this page and lose them?";

let unsaved = false;

/** Say that there is nothing left to lose, e.g. after saving and before navigating away. */
export function clearUnsaved(): void {
  unsaved = false;
}

/** True if nothing is unsaved or the person agrees to lose it. */
export function confirmLeave(): boolean {
  return !unsaved || window.confirm(MESSAGE);
}

/**
 * Ask before the page is left while `isDirty`: closing, reloading, in-app links and Back.
 * Only one per page may be enabled: they share one flag and one history entry.
 */
export function useUnsavedChanges(isDirty: boolean, enabled = true): void {
  const hasEntry = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    unsaved = isDirty;
    // Back cannot be cancelled. A second history entry for this page makes Back land here first.
    if (isDirty && !hasEntry.current) {
      hasEntry.current = true;
      history.pushState(history.state, "", location.href);
    }
    return clearUnsaved;
  }, [isDirty, enabled]);

  useEffect(() => {
    if (!enabled) return;
    const here = location.href;
    const entry: unknown = history.state;
    let leaving = false;

    function onBeforeUnload(event: BeforeUnloadEvent) {
      if (!unsaved) return;
      event.preventDefault();
      event.returnValue = true; // older browsers
    }

    function onClick(event: MouseEvent) {
      if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest("a") : null;
      if (!link?.href || link.hasAttribute("download")) return;
      if (link.target && link.target !== "_self") return;
      const url = new URL(link.href);
      if (url.origin !== location.origin) return; // a full page load: beforeunload asks
      if (url.pathname === location.pathname && url.search === location.search) return;
      if (confirmLeave()) return;
      event.preventDefault();
      event.stopPropagation();
    }

    function onPopState(event: PopStateEvent) {
      if (leaving || !hasEntry.current) return;
      if (location.href === here) {
        // From the second entry to the first: the router has nothing to do.
        event.stopImmediatePropagation();
        if (confirmLeave()) {
          leaving = true;
          clearUnsaved();
          history.back();
        } else {
          history.pushState(entry, "", here);
        }
      } else if (!confirmLeave()) {
        // Jumped further. The page is still shown, so give it its address back.
        event.stopImmediatePropagation();
        history.pushState(entry, "", here);
      }
    }

    // Capturing on window runs before the router's own handlers.
    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("click", onClick, true);
    window.addEventListener("popstate", onPopState, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("click", onClick, true);
      window.removeEventListener("popstate", onPopState, true);
    };
  }, [enabled]);
}
