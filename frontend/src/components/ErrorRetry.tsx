import { buttonClass } from "./buttonClass";

/** A load failure with a way to try again. */
export function ErrorRetry({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      <p role="alert">{message}</p>
      <button type="button" onClick={onRetry} className={buttonClass}>
        Retry
      </button>
    </div>
  );
}
