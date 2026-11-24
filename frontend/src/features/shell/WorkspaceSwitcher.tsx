import Link from "next/link";
import { type KeyboardEvent, type MouseEvent, useRef, useState } from "react";

import type { Workspace } from "@/features/workspaces/types";

type Props = {
  active: Workspace | undefined;
  workspaces: Workspace[];
  onNavigate: (event: MouseEvent) => void;
};

/** A disclosure with plain links, so it works with ordinary Tab and Enter. */
export function WorkspaceSwitcher({ active, workspaces, onNavigate }: Props) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key !== "Escape" || !open) return;
    event.stopPropagation(); // closes the list only, not the menu around it
    setOpen(false);
    button.current?.focus();
  }

  function choose(event: MouseEvent) {
    setOpen(false);
    onNavigate(event);
  }

  return (
    <div onKeyDown={onKeyDown}>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls="workspace-list"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 rounded-md border border-current px-3 py-2 text-left"
      >
        <span className="min-w-0 break-words">
          <span className="block text-sm">Workspace</span>{" "}
          <span className="line-clamp-2 font-medium">{active?.name ?? "None selected"}</span>
        </span>
        <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      <ul id="workspace-list" hidden={!open} className="mt-2 border-l border-current">
        {workspaces.map((workspace) => {
          const isActive = workspace.id === active?.id;
          return (
            <li key={workspace.id}>
              <Link
                href={`/workspaces/${workspace.id}`}
                onClick={choose}
                aria-current={isActive ? "true" : undefined}
                className={`block px-3 py-2 break-words ${isActive ? "font-semibold" : ""}`}
              >
                {workspace.name}
              </Link>
            </li>
          );
        })}
        <li>
          <Link href="/workspaces" onClick={choose} className="block px-3 py-2 underline">
            New workspace
          </Link>
        </li>
      </ul>
    </div>
  );
}
