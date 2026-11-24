import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

const nav = vi.hoisted(() => ({
  router: { replace: vi.fn() },
  pathname: "/workspaces/w2",
  params: {} as { id?: string },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => nav.router,
  usePathname: () => nav.pathname,
  useParams: () => nav.params,
}));

const one = { id: "w1", name: "One", role: "owner" };
const two = { id: "w2", name: "Two", role: "member" };
const KEY = "agently:last-workspace:u1";
let me: () => Response | Promise<Response>;
let list: () => Response | Promise<Response>;

function at(pathname: string, id?: string) {
  nav.pathname = pathname;
  nav.params = id ? { id } : {};
}

beforeEach(() => {
  localStorage.clear();
  me = () => Response.json({ id: "u1", email: "a@example.com" });
  list = () => Response.json([one, two]);
  vi.stubGlobal("fetch", async (url: string) => (url === "/api/auth/me" ? me() : list()));
  at("/workspaces/w2", "w2");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  nav.router.replace.mockReset();
});

const shell = () => <AppShell><p data-testid="child">page content</p></AppShell>; // new element, so a rerender is not skipped
const links = () =>
  within(screen.getByRole("navigation", { name: "Main" }))
    .getAllByRole("link")
    .map((link) => [link.textContent, link.getAttribute("href")]);
const switcher = () => screen.getByRole("button", { name: /^Workspace/ });

describe("AppShell", () => {
  it("shows the active workspace, its links and the account", async () => {
    render(shell());
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    expect(screen.queryByText("page content")).toBeNull();
    expect(await screen.findByText("page content")).toBeInTheDocument();
    expect(switcher()).toHaveTextContent("Two");
    expect(links()).toEqual([
      ["Dashboard", "/workspaces/w2"],
      ["My Agents", "/workspaces/w2/agents"],
      ["Settings", "/workspaces/w2/settings"],
      ["Account", "/account"],
    ]);
    const current = screen.getByRole("link", { name: "Dashboard" });
    expect(current).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Settings" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("a@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("remembers only the workspace id, under the user id", async () => {
    render(shell());
    await waitFor(() => expect(localStorage.getItem(KEY)).toBe("w2"));
    expect(Object.keys(localStorage)).toEqual([KEY]);
  });

  it("never shows or remembers another workspace for an unknown one", async () => {
    localStorage.setItem(KEY, "w1");
    at("/workspaces/other", "other");
    render(shell());
    await screen.findByText("page content");
    expect(switcher()).toHaveTextContent("None selected");
    expect(links()).toEqual([
      ["Dashboard", "/dashboard"],
      ["Account", "/account"],
    ]);
    expect(localStorage.getItem(KEY)).toBe("w1");
  });

  it("keeps the last-used workspace on pages outside a workspace", async () => {
    localStorage.setItem(KEY, "w2");
    at("/account");
    render(shell());
    await screen.findByText("page content");
    expect(switcher()).toHaveTextContent("Two");
  });

  it("leaves account and sign out without any workspace", async () => {
    list = () => Response.json([]);
    at("/workspaces");
    render(shell());
    await screen.findByText("page content");
    expect(links()).toEqual([["Account", "/account"]]);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("works when storage throws", async () => {
    const denied = () => {
      throw new DOMException("denied", "SecurityError");
    };
    vi.stubGlobal("localStorage", { getItem: denied, setItem: denied });
    const view = render(shell());
    await screen.findByText("page content");
    at("/account");
    view.rerender(<AppShell>account page</AppShell>);
    await waitFor(() => expect(switcher()).toHaveTextContent("One"));
  });

  it("refreshes after a navigation, and keeps showing the page if that fails", async () => {
    const view = render(shell());
    await screen.findByText("page content");
    list = () => Response.json([one, { ...two, name: "Renamed" }]);
    at("/workspaces/w2/settings", "w2");
    view.rerender(<AppShell>settings</AppShell>);
    await waitFor(() => expect(switcher()).toHaveTextContent("Renamed"));
    const failed = vi.fn(() => Promise.reject(new TypeError("down")));
    list = failed;
    at("/workspaces/w2", "w2");
    view.rerender(shell());
    await waitFor(() => expect(failed).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve));
    expect(screen.getByText("page content")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ignores an answer that arrives after a newer one", async () => {
    let answerOld!: (response: Response) => void;
    list = () => new Promise<Response>((resolve) => (answerOld = resolve));
    const view = render(shell());
    await waitFor(() => expect(answerOld).toBeDefined());
    list = () => Response.json([one, two]);
    at("/workspaces/w1", "w1");
    view.rerender(shell());
    await screen.findByText("page content");
    answerOld(Response.json([]));
    await new Promise((resolve) => setTimeout(resolve));
    expect(switcher()).toHaveTextContent("One");
  });

  it("goes to login when signed out, without showing the page", async () => {
    me = () =>
      Response.json({ error: { code: "authentication_required", message: "x" } }, { status: 401 });
    render(shell());
    await waitFor(() => expect(nav.router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("page content")).toBeNull();
  });

  it("offers a retry, not a login redirect, when the server is unreachable", async () => {
    list = () => Promise.reject(new TypeError("down"));
    render(shell());
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    expect(nav.router.replace).not.toHaveBeenCalled();
    list = () => Response.json([one, two]);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("page content")).toBeInTheDocument();
  });

  it("lists workspaces in the switcher and closes it with Escape, menu left open", async () => {
    render(shell());
    const menu = await screen.findByRole("button", { name: "Menu" });
    fireEvent.click(menu);
    expect(screen.queryByRole("link", { name: "New workspace" })).toBeNull();
    fireEvent.click(switcher());
    expect(switcher()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "One" })).toHaveAttribute("href", "/workspaces/w1");
    expect(screen.getByRole("link", { name: "Two" })).toHaveAttribute("aria-current", "true");
    const create = screen.getByRole("link", { name: "New workspace" });
    expect(create).toHaveAttribute("href", "/workspaces");
    create.focus();
    fireEvent.keyDown(create, { key: "Escape" });
    expect(switcher()).toHaveAttribute("aria-expanded", "false");
    expect(switcher()).toHaveFocus();
    expect(menu).toHaveAttribute("aria-expanded", "true");
  });

  it("closes the menu with Escape and returns focus to its button", async () => {
    render(shell());
    const menu = await screen.findByRole("button", { name: "Menu" });
    fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(screen.getByRole("link", { name: "Settings" }), { key: "Escape" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu).toHaveFocus();
  });

  it("closes the menu and moves focus to the page when a link is followed", async () => {
    render(shell());
    const menu = await screen.findByRole("button", { name: "Menu" });
    fireEvent.click(menu);
    const link = screen.getByRole("link", { name: "Settings" });
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("closes the switcher when a workspace is chosen", async () => {
    render(shell());
    await screen.findByText("page content");
    fireEvent.click(switcher());
    const link = screen.getByRole("link", { name: "One" });
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    expect(switcher()).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("leaves the menu alone when a link is opened in a new tab", async () => {
    render(shell());
    const menu = await screen.findByRole("button", { name: "Menu" });
    fireEvent.click(menu);
    const link = screen.getByRole("link", { name: "Settings" });
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link, { ctrlKey: true });
    expect(menu).toHaveAttribute("aria-expanded", "true");
  });

  it("goes to login when the session ends during use", async () => {
    render(shell());
    await screen.findByText("page content");
    me = () =>
      Response.json({ error: { code: "authentication_required", message: "x" } }, { status: 401 });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(nav.router.replace).toHaveBeenCalledWith("/login"));
  });

  it("drops everything shown for the previous account", async () => {
    const view = render(shell());
    const before = await screen.findByTestId("child");
    me = () => Response.json({ id: "u2", email: "b@example.com" });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(await screen.findByText("b@example.com")).toBeInTheDocument();
    expect(screen.getByTestId("child")).not.toBe(before); // remounted
    me = () => Response.json({ id: "u3", email: "c@example.com" });
    list = () => Promise.reject(new TypeError("down"));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(view.container).not.toHaveTextContent("b@example.com");
  });

  it("hides a page restored by Back until the session is confirmed", async () => {
    const view = render(shell());
    await screen.findByText("page content");
    me = () => new Promise<Response>(() => undefined);
    const event = Object.assign(new Event("pageshow"), { persisted: true });
    fireEvent(window, event);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    expect(view.container).not.toHaveTextContent("a@example.com");
  });

  it("matches an id written in upper case", async () => {
    at("/workspaces/W2", "W2");
    render(shell());
    await screen.findByText("page content");
    expect(switcher()).toHaveTextContent("Two");
  });
});
