// Typed API client. All calls go to same-origin /api/*, which Next.js rewrites to the backend.

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string | null;
  };
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class NetworkError extends Error {
  constructor() {
    super("Could not reach the server. Check your connection and try again.");
    this.name = "NetworkError";
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ApiErrorBody).error?.code === "string"
  );
}

/**
 * Fetch JSON from the backend. Throws NetworkError when the server is unreachable and
 * ApiError for non-2xx responses (unless `acceptStatuses` includes the status).
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit & { acceptStatuses?: number[] } = {},
): Promise<{ status: number; data: T }> {
  const { acceptStatuses = [], ...requestInit } = init;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      credentials: "same-origin",
      ...requestInit,
      headers: { Accept: "application/json", ...requestInit.headers },
    });
  } catch {
    throw new NetworkError();
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.ok || acceptStatuses.includes(response.status)) {
    return { status: response.status, data: body as T };
  }
  if (isApiErrorBody(body)) {
    throw new ApiError(response.status, body.error.code, body.error.message, body.error.details);
  }
  // Proxy errors (e.g. backend down behind the Next.js rewrite) have no JSON body.
  if (response.status >= 500) throw new NetworkError();
  throw new ApiError(response.status, "unknown_error", "Request failed.");
}

/** POST JSON. The session cookie is HttpOnly: the browser sends it, scripts never see it. */
export function apiPost<T>(path: string, body?: unknown): Promise<{ status: number; data: T }> {
  return apiFetch<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** Text to show for any failed request. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError) return error.message;
  return "Something went wrong. Please try again.";
}
