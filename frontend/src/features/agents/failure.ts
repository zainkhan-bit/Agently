import { ApiError, errorMessage } from "@/lib/api";

/** Text for a failed change. Without a clear answer from the server it may have happened. */
export function changeFailure(error: unknown, check: string): string {
  // 503 "busy" says that nothing was changed; other 5xx do not say how far the change got.
  if (error instanceof ApiError && (error.status < 500 || error.code === "busy")) {
    return errorMessage(error);
  }
  return `${errorMessage(error)} The change may have been made: ${check}`;
}
