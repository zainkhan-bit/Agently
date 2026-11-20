import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ServiceStatus } from "./ServiceStatus";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ServiceStatus", () => {
  it("shows loading, then ready", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(200, { status: "ready", checks: { database: "ok" } }),
      ),
    );
    render(<ServiceStatus />);
    expect(screen.getByText("Checking services…")).toBeInTheDocument();
    expect(await screen.findByText("All services are ready.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/health/ready", expect.anything());
  });

  it("explains a missing database configuration", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(503, { status: "not_ready", checks: { database: "not_configured" } }),
      ),
    );
    render(<ServiceStatus />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Service degraded");
    expect(alert).toHaveTextContent("DATABASE_URL");
  });

  it("explains an unreachable database", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(503, { status: "not_ready", checks: { database: "unavailable" } }),
      ),
    );
    render(<ServiceStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent("PostgreSQL is running");
  });

  it("shows an offline message and retries successfully", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse(200, { status: "ready", checks: { database: "ok" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ServiceStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent("API is not reachable");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("All services are ready.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("treats a proxy error without JSON as offline", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad gateway", { status: 502 })));
    render(<ServiceStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent("API is not reachable");
  });
});
