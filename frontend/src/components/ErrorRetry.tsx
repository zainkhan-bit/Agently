import { buttonClass } from "./buttonClass";
import { PageHeading } from "./PageHeading";

/** A page load failure with a way to try again. */
export function ErrorRetry({ message, onRetry }: { message: string; onRetry: () => void }) {
  function retry() {
    // This button goes away while loading: keep focus on the page, not lost.
    document.getElementById("content")?.focus();
    onRetry();
  }
  return (
    <div className="flex flex-col gap-4">
      <PageHeading>Something went wrong</PageHeading>
      <p role="alert">{message}</p>
      <button type="button" onClick={retry} className={buttonClass}>
        Retry
      </button>
    </div>
  );
}
