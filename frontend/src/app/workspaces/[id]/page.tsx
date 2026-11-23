import { WorkspaceView } from "@/features/workspaces/WorkspaceView";

export default async function WorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className="mx-auto min-h-screen max-w-md px-4 py-16">
      <WorkspaceView key={id} id={id} />
    </main>
  );
}
