/** A stored time in the reader's own time zone and language. */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "at an unknown time";
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
