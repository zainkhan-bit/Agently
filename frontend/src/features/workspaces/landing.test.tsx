import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HomeNav } from "@/features/auth/HomeNav";

import { DashboardView } from "./DashboardView";
import { OpenDashboard } from "./OpenDashboard";

const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const one = { id: "w1", name: "One", role: "owner" };
const two = { id: "w2", name: "Two", role: "member" };
const unauthorized = () =>
  Response.json({ error: { code: "authentication_required", message: "x" } }, { status: 401 });
const down = () => Promise.reject(new TypeError("down"));
let routes: Record<string, () => Response | Promise<Response>>;

beforeEach(() => {
  localStorage.clear();
  routes = {
    "/api/auth/me": () => Response.json({ id: "u1", email: "a@example.com" }),
    "/api/workspaces": () => Response.json([one, two]),
    "/api/workspaces/w2": () => Response.json(two),
    "/api/workspaces/w2/members": () =>
      Response.json([
        { user_id: "u1", email: "a@example.com", role: "member" },
        { user_id: "u2", email: "b@example.com", role: "owner" },
      ]),
  };
  vi.stubGlobal("fetch", async (url: string) => routes[url]());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  router.replace.mockReset();
});

describe("OpenDashboard", () => {
  async function opens(path: string) {
    render(<OpenDashboard />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith(path));
  }

  it("opens the first workspace when none is remembered", () => opens("/workspaces/w1"));

  it("opens the remembered workspace", async () => {
    localStorage.setItem("agently:last-workspace:u1", "w2");
    await opens("/workspaces/w2");
  });

  it("ignores another account's remembered workspace", async () => {
    localStorage.setItem("agently:last-workspace:u2", "w2");
    await opens("/workspaces/w1");
  });

  it("ignores a remembered workspace the person has lost", async () => {
    localStorage.setItem("agently:last-workspace:u1", "gone");
    await opens("/workspaces/w1");
  });

  it("opens the create form without any workspace", async () => {
    routes["/api/workspaces"] = () => Response.json([]);
    await opens("/workspaces");
  });

  it("works when storage throws", async () => {
    vi.stubGlobal("localStorage", {
      getItem() {
        throw new DOMException("denied", "SecurityError");
      },
    });
    await opens("/workspaces/w1");
  });

  it("goes to login when signed out", async () => {
    routes["/api/auth/me"] = unauthorized;
    await opens("/login");
  });

  it("offers a retry when the server is unreachable", async () => {
    routes["/api/workspaces"] = down;
    render(<OpenDashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    expect(router.replace).not.toHaveBeenCalled();
    routes["/api/workspaces"] = () => Response.json([one]);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/workspaces/w1"));
  });
});

describe("DashboardView", () => {
  it("shows this workspace's real values and no controls", async () => {
    render(<DashboardView id="w2" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading dashboard…");
    expect(await screen.findByRole("heading", { level: 1, name: "Two" })).toBeInTheDocument();
    expect(screen.getByText("Your role").nextSibling).toHaveTextContent("member");
    expect(screen.getByText("Members").nextSibling).toHaveTextContent("2");
    expect(screen.getByText(/Creating agents is not available yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows not found instead of redirecting", async () => {
    routes["/api/workspaces/w2"] = () =>
      Response.json({ error: { code: "not_found", message: "x" } }, { status: 404 });
    render(<DashboardView id="w2" />);
    expect(await screen.findByText("Workspace not found")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("goes to login when signed out", async () => {
    routes["/api/workspaces/w2"] = unauthorized;
    render(<DashboardView id="w2" />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });

  it("offers a retry when the server is unreachable", async () => {
    const members = routes["/api/workspaces/w2/members"];
    routes["/api/workspaces/w2/members"] = down;
    render(<DashboardView id="w2" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    routes["/api/workspaces/w2/members"] = members;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Two" })).toBeInTheDocument();
  });
});

describe("HomeNav", () => {
  it("offers the dashboard to a signed-in visitor", async () => {
    render(<HomeNav />);
    const link = await screen.findByRole("link", { name: "Go to dashboard" });
    expect(link).toHaveAttribute("href", "/dashboard");
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
  });

  it.each([
    ["signed out", unauthorized],
    ["unreachable", down],
  ])("offers sign in when %s", async (_, response) => {
    const called = vi.fn(response);
    routes["/api/auth/me"] = called;
    render(<HomeNav />);
    await waitFor(() => expect(called).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve));
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Go to dashboard" })).toBeNull();
  });
});
