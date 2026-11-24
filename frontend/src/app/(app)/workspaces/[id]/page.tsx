import type { Metadata } from "next";

import { DashboardView } from "@/features/workspaces/DashboardView";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DashboardView key={id} id={id} />;
}
