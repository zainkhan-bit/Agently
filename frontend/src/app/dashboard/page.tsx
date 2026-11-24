import type { Metadata } from "next";

import { OpenDashboard } from "@/features/workspaces/OpenDashboard";

export const metadata: Metadata = { title: "Dashboard" };

export default function OpenDashboardPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-16">
      <OpenDashboard />
    </main>
  );
}
