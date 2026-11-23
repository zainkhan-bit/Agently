import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountView } from "./AccountView";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => {
  const router = { replace };
  return { useRouter: () => router };
});

const fetchMock = vi.fn();
const signedIn = () => Response.json({ id: "1", email: "a@example.com" });

beforeEach(() => vi.stubGlobal("fetch", fetchMock));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  replace.mockReset();
});

describe("AccountView", () => {
  it("shows a loading line, then who is signed in", async () => {
    fetchMock.mockResolvedValueOnce(signedIn());
    render(<AccountView />);
    expect(screen.getByText("Checking your session…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
    expect(await screen.findByText("Signed in as a@example.com")).toBeInTheDocument();
  });

  it("goes to login when there is no session", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({ error: { code: "authentication_required", message: "x" } }, { status: 401 }),
    );
    render(<AccountView />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("offers a retry, not a login redirect, when the server is unreachable", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("down")).mockResolvedValueOnce(signedIn());
    render(<AccountView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    expect(replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Signed in as a@example.com")).toBeInTheDocument();
  });

  it("signs out with a POST, then goes to login", async () => {
    fetchMock
      .mockResolvedValueOnce(signedIn())
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<AccountView />);
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/auth/logout",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("stays on the page when sign-out fails", async () => {
    fetchMock.mockResolvedValueOnce(signedIn()).mockRejectedValueOnce(new TypeError("down"));
    render(<AccountView />);
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You may still be signed in");
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByText("Signed in as a@example.com")).toBeInTheDocument();
  });
});
