import Link from "next/link";

import { PageHeading } from "@/components/PageHeading";

export function WorkspaceMissing() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeading title="Workspace not found">Workspace not found</PageHeading>
      <p>It does not exist, or you are not a member.</p>
      <Link href="/workspaces" className="underline">
        All workspaces
      </Link>
    </div>
  );
}
