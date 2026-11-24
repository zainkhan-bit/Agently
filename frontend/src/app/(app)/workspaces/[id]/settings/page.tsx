import type { Metadata } from "next";

import { WorkspaceSettings } from "@/features/workspaces/WorkspaceSettings";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WorkspaceSettings key={id} id={id} />;
}
