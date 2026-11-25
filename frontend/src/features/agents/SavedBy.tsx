/** Who saved a version, and when. The server sends an email only for current members. */
export function SavedBy({ version }: { version: { saved_by: string | null; created_at: string } }) {
  return (
    <p>
      Saved by {version.saved_by ?? "Former member"},{" "}
      <time dateTime={version.created_at}>{new Date(version.created_at).toLocaleString()}</time>
    </p>
  );
}
