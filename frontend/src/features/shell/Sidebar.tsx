import Link from "next/link";
import type { MouseEvent } from "react";

import { SignOutButton } from "@/features/auth/SignOutButton";
import type { User } from "@/features/auth/types";
import type { Workspace } from "@/features/workspaces/types";
import { pickWorkspace } from "@/lib/lastWorkspace";

import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

type Props = {
  user: User;
  workspaces: Workspace[];
  /** The workspace id in the URL, if the page has one. */
  routeId: string | undefined;
  pathname: string;
  onNavigate: (event: MouseEvent) => void;
};

export function Sidebar({ user, workspaces, routeId, pathname, onNavigate }: Props) {
  // A URL naming an unknown workspace has no active workspace: never show another one as active.
  const active = routeId
    ? workspaces.find(({ id }) => id === routeId)
    : pickWorkspace(user.id, workspaces);

  const links = [{ href: "/account", label: "Account" }];
  if (active) {
    links.unshift(
      { href: `/workspaces/${active.id}`, label: "Dashboard" },
      { href: `/workspaces/${active.id}/agents`, label: "My Agents" },
      { href: `/workspaces/${active.id}/settings`, label: "Settings" },
    );
  } else if (workspaces.length > 0) {
    links.unshift({ href: "/dashboard", label: "Dashboard" });
  }

  return (
    <div className="flex flex-col gap-6 px-4 pb-4">
      <WorkspaceSwitcher active={active} workspaces={workspaces} onNavigate={onNavigate} />
      <nav aria-label="Main">
        <ul className="flex flex-col">
          {links.map(({ href, label }) => {
            const isPage = pathname === href;
            // The pages of one agent belong to My Agents.
            const isCurrent =
              isPage || (href.endsWith("/agents") && pathname.startsWith(`${href}/`));
            return (
              <li key={href}>
                <Link
                  href={href}
                  onClick={onNavigate}
                  aria-current={isPage ? "page" : isCurrent ? "true" : undefined}
                  className={`block border-l-4 px-3 py-2 ${
                    isCurrent ? "border-current font-semibold" : "border-transparent"
                  }`}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="flex flex-col gap-2">
        <p className="text-sm break-words">{user.email}</p>
        <SignOutButton />
      </div>
    </div>
  );
}
