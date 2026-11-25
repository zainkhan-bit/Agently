import type { MouseEvent } from "react";

/** For links inside the page: without this, focus would be lost with the link. */
export function focusContentOnFollow(event: MouseEvent) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  document.getElementById("content")?.focus();
}
