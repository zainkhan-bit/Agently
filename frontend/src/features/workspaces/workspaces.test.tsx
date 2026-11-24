import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceList } from "./WorkspaceList";
import { WorkspaceSettings } from "./WorkspaceSettings";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const team = { id: "w1", name: "Team", role: "owner" };
const members = [{ user_id: "u1", email: "a@example.com", role: "owner" }];
let routes: Record<string, () => Response | Promise<Response>>;
const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
  routes[`${init?.method ?? "GET"} ${url}`](),
);

function fail(status: number, code: string, message: string, details?: unknown) {
  return Response.json({ error: { code, message, details } }, { status });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  routes = {
    "GET /api/workspaces": () => Response.json([team]),
    "GET /api/workspaces/w1": () => Response.json(team),
    "GET /api/workspaces/w1/members": () => Response.json(members),
  };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockClear();
  router.replace.mockReset();
  router.push.mockReset();
});

describe("WorkspaceList", () => {
  it("lists workspaces with links and roles", async () => {
    render(<WorkspaceList />);
    expect(screen.getByText("Loading workspaces…")).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "Team" });
    expect(link).toHaveAttribute("href", "/workspaces/w1");
  });

  it("invites someone with none to create their first", async () => {
    routes["GET /api/workspaces"] = () => Response.json([]);
    render(<WorkspaceList />);
    expect(await screen.findByText(/Create your first workspace/)).toBeInTheDocument();
  });

  it("creates a workspace once and opens it", async () => {
    routes["POST /api/workspaces"] = () => Response.json({ ...team, id: "w2" }, { status: 201 });
    render(<WorkspaceList />);
    const input = await screen.findByLabelText("New workspace name");
    fireEvent.change(input, { target: { value: "New" } });
    fireEvent.submit(input.closest("form")!);
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/workspaces/w2"));
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(JSON.parse(posts[0][1]!.body as string)).toEqual({ name: "New" });
  });

  it.each([
    [
      () =>
        fail(422, "validation_error", "Some fields are invalid.", [
          { loc: ["body", "name"], msg: "Name must be 1 to 100 characters." },
        ]),
      "Name must be 1 to 100 characters.",
    ],
    [() => fail(409, "workspace_limit", "A person can own at most 20 workspaces."), "at most 20"],
  ])("shows why creation failed (%#)", async (response, text) => {
    routes["POST /api/workspaces"] = response;
    render(<WorkspaceList />);
    fireEvent.click(await screen.findByRole("button", { name: "Create workspace" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.getByRole("button", { name: "Create workspace" })).toBeEnabled();
  });

  it("does not navigate when the answer arrives after leaving the page", async () => {
    let answer!: (response: Response) => void;
    routes["POST /api/workspaces"] = () => new Promise<Response>((resolve) => (answer = resolve));
    const view = render(<WorkspaceList />);
    fireEvent.click(await screen.findByRole("button", { name: "Create workspace" }));
    await waitFor(() => expect(answer).toBeDefined());
    view.unmount();
    answer(Response.json(team, { status: 201 }));
    await new Promise((resolve) => setTimeout(resolve));
    expect(router.push).not.toHaveBeenCalled();
  });

  it("goes to login when signed out", async () => {
    routes["GET /api/workspaces"] = () => fail(401, "authentication_required", "x");
    render(<WorkspaceList />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });

  it("only goes to login when the session ends before creating", async () => {
    routes["POST /api/workspaces"] = () => fail(401, "authentication_required", "Sign in.");
    render(<WorkspaceList />);
    fireEvent.click(await screen.findByRole("button", { name: "Create workspace" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
  });

  it("offers a retry when the server is unreachable", async () => {
    routes["GET /api/workspaces"] = () => Promise.reject(new TypeError("down"));
    render(<WorkspaceList />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    routes["GET /api/workspaces"] = () => Response.json([team]);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "Team" })).toBeInTheDocument();
  });
});

describe("WorkspaceSettings", () => {
  it("shows the name, role and members", async () => {
    render(<WorkspaceSettings id="w1" />);
    expect(await screen.findByText("Team")).toBeInTheDocument();
    expect(screen.getByText("Your role: owner")).toBeInTheDocument();
    expect(screen.getByText("a@example.com (owner)")).toBeInTheDocument();
  });

  it.each([404, 422])("shows not found for a %i", async (status) => {
    routes["GET /api/workspaces/w1"] = () => fail(status, "x", "x");
    render(<WorkspaceSettings id="w1" />);
    expect(await screen.findByText("Workspace not found")).toBeInTheDocument();
  });

  it("cannot be steered to another endpoint by the id", async () => {
    routes["GET /api/workspaces/..%2Fauth%2Fme"] = () => fail(404, "x", "x");
    routes["GET /api/workspaces/..%2Fauth%2Fme/members"] = () => fail(404, "x", "x");
    render(<WorkspaceSettings id="../auth/me" />);
    expect(await screen.findByText("Workspace not found")).toBeInTheDocument();
  });

  it("deletes only after the exact name is typed", async () => {
    routes["DELETE /api/workspaces/w1"] = () => new Response(null, { status: 204 });
    render(<WorkspaceSettings id="w1" />);
    const input = await screen.findByLabelText("Workspace name");
    const button = screen.getByRole("button", { name: "Delete permanently" });
    for (const wrong of ["", "team", "Team "]) {
      fireEvent.change(input, { target: { value: wrong } });
      expect(button).toBeDisabled();
    }
    fireEvent.change(input, { target: { value: "Team" } });
    fireEvent.click(button);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("stays and explains when deletion fails", async () => {
    routes["DELETE /api/workspaces/w1"] = () => fail(403, "permission_denied", "No permission.");
    render(<WorkspaceSettings id="w1" />);
    const input = await screen.findByLabelText("Workspace name");
    fireEvent.change(input, { target: { value: "Team" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No permission.");
    expect(router.replace).not.toHaveBeenCalled();
  });

  async function tryToDelete() {
    render(<WorkspaceSettings id="w1" />);
    const input = await screen.findByLabelText("Workspace name");
    fireEvent.change(input, { target: { value: "Team" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  }

  it("only goes to login when the session ends before deleting", async () => {
    routes["DELETE /api/workspaces/w1"] = () => fail(401, "authentication_required", "Sign in.");
    await tryToDelete();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("leaves for the not-found page when the workspace is already gone", async () => {
    routes["DELETE /api/workspaces/w1"] = () => fail(404, "not_found", "x");
    await tryToDelete();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/workspaces/w1"));
  });

  it("offers no delete to a member", async () => {
    routes["GET /api/workspaces/w1"] = () => Response.json({ ...team, role: "member" });
    render(<WorkspaceSettings id="w1" />);
    expect(await screen.findByText("Your role: member")).toBeInTheDocument();
    expect(screen.queryByText("Delete workspace")).toBeNull();
  });
});
