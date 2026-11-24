import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/features/shell/AppShell";
import { clearUnsaved } from "@/lib/unsavedChanges";

import { AgentList } from "./AgentList";
import { AgentView } from "./AgentView";
import { EditAgent } from "./EditAgent";
import { NewAgent } from "./NewAgent";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/workspaces/w1/agents/new",
  useParams: () => ({ id: "w1" }),
}));

const LIST = "/api/workspaces/w1/agents";
const ONE = `${LIST}/a1`;
const agent = {
  id: "a1",
  status: "active",
  version: 3,
  name: "Helper",
  purpose: "Help people",
  description: null as string | null,
  instructions: "Be kind.",
};
const currentPage = `GET ${LIST}?archived=false&limit=100&offset=0`;
let routes: Record<string, () => Response | Promise<Response>>;
const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
  routes[`${init?.method ?? "GET"} ${url}`](),
);
const confirmMock = vi.fn(() => true);

const fail = (status: number, code: string, message: string, details?: unknown) =>
  Response.json({ error: { code, message, details } }, { status });
const down = () => Promise.reject(new TypeError("down"));
const role = (value: string) => () => Response.json({ id: "w1", name: "Team", role: value });
const sent = (method: string) =>
  fetchMock.mock.calls.filter(([, init]) => init?.method === method);
const button = (name: string) => screen.getByRole("button", { name });
const type = (label: RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const submit = () => fireEvent.submit(document.querySelector("form")!);
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("confirm", confirmMock);
  routes = {
    "GET /api/workspaces/w1": role("owner"),
    "GET /api/workspaces/w1/members": () => Response.json([]),
    [`GET ${ONE}`]: () => Response.json(agent),
    [currentPage]: () => Response.json({ items: [agent], total: 1 }),
  };
});

afterEach(() => {
  cleanup();
  clearUnsaved();
  vi.unstubAllGlobals();
  fetchMock.mockClear();
  confirmMock.mockReset().mockReturnValue(true);
  router.replace.mockReset();
  router.push.mockReset();
});

describe("plain text", () => {
  const evil = (field: string) => `<script>window.hit=1</script><img src=x onerror=alert(1)> ${field}`;
  const hostile = {
    ...agent,
    name: evil("name"),
    purpose: evil("purpose"),
    description: evil("description"),
    instructions: evil("instructions"),
  };

  function expectInert(container: HTMLElement) {
    expect(container.querySelector("script, img")).toBeNull();
  }

  it("shows markup literally in the list", async () => {
    routes[currentPage] = () => Response.json({ items: [hostile], total: 1 });
    const { container } = render(<AgentList workspaceId="w1" archived={false} />);
    expect(await screen.findByText(hostile.name)).toBeInTheDocument();
    expect(screen.getByText(hostile.purpose)).toBeInTheDocument();
    expectInert(container);
  });

  it("shows markup literally on the agent page and in its title", async () => {
    routes[`GET ${ONE}`] = () => Response.json(hostile);
    const { container } = render(<AgentView workspaceId="w1" agentId="a1" />);
    for (const text of [hostile.name, hostile.purpose, hostile.description, hostile.instructions]) {
      expect(await screen.findByText(text)).toBeInTheDocument();
    }
    expect(document.title).toContain(hostile.name);
    expectInert(container);
  });

  it("saves markup unchanged and shows it literally in the form", async () => {
    routes[`GET ${ONE}`] = () => Response.json(hostile);
    routes[`PATCH ${ONE}`] = () => Response.json(hostile);
    const { container } = render(<EditAgent workspaceId="w1" agentId="a1" />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(hostile.name);
    for (const field of ["Name", "Purpose", "Description", "Instructions"]) {
      expect(screen.getByLabelText(new RegExp(field))).toHaveValue(evil(field.toLowerCase()));
    }
    expectInert(container);
    submit();
    await waitFor(() => expect(sent("PATCH")).toHaveLength(1));
    expect(JSON.parse(sent("PATCH")[0][1]!.body as string)).toMatchObject({
      name: hostile.name,
      instructions: hostile.instructions,
    });
  });

  it("no source file inserts HTML", () => {
    const root = path.resolve(__dirname, "../..");
    const files = readdirSync(root, { recursive: true, encoding: "utf8" }).filter(
      (file) => /\.tsx?$/.test(file) && !file.includes(".test."),
    );
    expect(files.length).toBeGreaterThan(20);
    const bad = files.filter((file) =>
      /dangerouslySetInnerHTML|innerHTML|insertAdjacentHTML|document\.write/.test(
        readFileSync(path.join(root, file), "utf8"),
      ),
    );
    expect(bad).toEqual([]);
  });
});

describe("AgentList", () => {
  it("lists agents with their status in words", async () => {
    render(<AgentList workspaceId="w1" archived={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading agents…");
    expect(await screen.findByRole("link", { name: "Helper" })).toHaveAttribute(
      "href",
      "/workspaces/w1/agents/a1",
    );
    expect(screen.getByText("Status: Active")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Current" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each([
    [false, "No current agents"],
    [true, "No archived agents"],
  ])("has an empty state (archived %s)", async (archived, text) => {
    routes[`GET ${LIST}?archived=${archived}&limit=100&offset=0`] = () =>
      Response.json({ items: [], total: 0 });
    render(<AgentList workspaceId="w1" archived={archived} />);
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New agent" })).toBeInTheDocument();
  });

  it("reaches every agent, showing each once", async () => {
    const many = Array.from({ length: 100 }, (_, n) => ({ ...agent, id: `a${n}`, name: `N${n}` }));
    const more = [many[99], { ...agent, id: "last", name: "Last" }];
    routes[currentPage] = () => Response.json({ items: many, total: 102 });
    routes[`GET ${LIST}?archived=false&limit=100&offset=100`] = down;
    render(<AgentList workspaceId="w1" archived={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Show more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    routes[`GET ${LIST}?archived=false&limit=100&offset=100`] = () =>
      Response.json({ items: more, total: 102 });
    fireEvent.click(button("Show more"));
    expect(await screen.findByText("Last")).toBeInTheDocument();
    expect(screen.getAllByText("N99")).toHaveLength(1);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each([404, 422])("shows not found for a %i", async (status) => {
    routes[currentPage] = () => fail(status, "x", "x");
    render(<AgentList workspaceId="w1" archived={false} />);
    expect(await screen.findByText("Workspace not found")).toBeInTheDocument();
  });

  it("goes to login when signed out and retries when unreachable", async () => {
    routes[currentPage] = down;
    render(<AgentList workspaceId="w1" archived={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    routes[currentPage] = () => fail(401, "authentication_required", "x");
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });
});

describe("AgentView", () => {
  const show = async () => {
    render(<AgentView workspaceId="w1" agentId="a1" />);
    await screen.findByRole("heading", { level: 1 });
  };

  it.each([
    ["active", ["Duplicate", "Pause", "Archive"], true],
    ["paused", ["Duplicate", "Resume", "Archive"], true],
    ["archived", ["Duplicate", "Restore"], false],
  ])("offers what fits an agent that is %s", async (status, names, editable) => {
    routes[`GET ${ONE}`] = () => Response.json({ ...agent, status });
    await show();
    const all = screen.getAllByRole("button").map((item) => item.textContent);
    expect(all).toEqual([...names, "Delete permanently"]);
    expect(screen.queryByRole("link", { name: "Edit" }) !== null).toBe(editable);
  });

  it("does not offer delete to members", async () => {
    routes["GET /api/workspaces/w1"] = role("member");
    await show();
    expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull();
  });

  it("changes the status only when the server has answered, and keeps focus", async () => {
    let answer!: (response: Response) => void;
    routes[`POST ${ONE}/pause`] = () => new Promise<Response>((resolve) => (answer = resolve));
    await show();
    button("Pause").focus();
    fireEvent.click(button("Pause"));
    fireEvent.click(button("Pause"));
    expect(screen.getByText("Status: Active.")).toBeInTheDocument();
    await waitFor(() => expect(answer).toBeDefined());
    answer(Response.json({ ...agent, status: "paused" }));
    expect(await screen.findByText("Status: Paused.")).toBeInTheDocument();
    expect(sent("POST")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("The agent is now paused");
    expect(button("Resume")).toHaveFocus();
  });

  it.each([
    [() => fail(503, "busy", "The workspace is busy. Nothing was changed."), /busy/, false],
    [down, /Could not reach the server/, true],
    [() => fail(500, "internal_error", "Something went wrong."), /Something went wrong/, true],
  ])("a failed change changes nothing on screen (%#)", async (response, text, unknown) => {
    routes[`POST ${ONE}/pause`] = response;
    await show();
    fireEvent.click(button("Pause"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(text);
    expect(/may have been made/.test(alert.textContent!)).toBe(unknown);
    expect(screen.getByText("Status: Active.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("shows the real status after a conflict", async () => {
    routes[`POST ${ONE}/pause`] = () => {
      routes[`GET ${ONE}`] = () => Response.json({ ...agent, status: "archived" });
      return fail(409, "status_conflict", "Cannot pause an agent that is archived.");
    };
    await show();
    fireEvent.click(button("Pause"));
    expect(await screen.findByText("Status: Archived.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Cannot pause");
  });

  it("shows not found when the agent has gone meanwhile", async () => {
    routes[`POST ${ONE}/pause`] = () => {
      routes[`GET ${ONE}`] = () => fail(404, "not_found", "x");
      return fail(404, "not_found", "x");
    };
    await show();
    fireEvent.click(button("Pause"));
    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
  });

  it.each([404, 422])("an agent of another workspace is not found (%i)", async (status) => {
    routes[`GET ${ONE}`] = () => fail(status, "x", "x");
    render(<AgentView workspaceId="w1" agentId="a1" />);
    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
  });

  it("a workspace that is not the person's own is not found", async () => {
    routes["GET /api/workspaces/w1"] = () => fail(404, "x", "x");
    routes[`GET ${ONE}`] = () => fail(404, "x", "x");
    render(<AgentView workspaceId="w1" agentId="a1" />);
    expect(await screen.findByText("Workspace not found")).toBeInTheDocument();
  });

  it("cannot be steered to another endpoint by the id", async () => {
    routes["GET /api/workspaces/w1/agents/..%2F..%2Fx"] = () => fail(404, "x", "x");
    render(<AgentView workspaceId="w1" agentId="../../x" />);
    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
  });

  it("duplicates and opens the copy", async () => {
    routes[`POST ${ONE}/duplicate`] = () => Response.json({ ...agent, id: "a2" }, { status: 201 });
    await show();
    fireEvent.click(button("Duplicate"));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/workspaces/w1/agents/a2"));
  });

  it("deletes only after the exact name, and leaves only when confirmed", async () => {
    routes[`DELETE ${ONE}`] = () => fail(403, "permission_denied", "No permission.");
    await show();
    expect(button("Delete permanently")).toBeDisabled();
    type(/Agent name/, "helper");
    expect(button("Delete permanently")).toBeDisabled();
    type(/Agent name/, "Helper");
    fireEvent.click(button("Delete permanently"));
    expect(await screen.findByRole("alert")).toHaveTextContent("No permission.");
    expect(router.replace).not.toHaveBeenCalled();
    routes[`DELETE ${ONE}`] = () => new Response(null, { status: 204 });
    await waitFor(() =>
      expect(button("Delete permanently")).toHaveAttribute("aria-disabled", "false"),
    );
    fireEvent.click(button("Delete permanently"));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/workspaces/w1/agents"));
  });

  it("stops offering delete to an owner who was demoted meanwhile", async () => {
    routes[`DELETE ${ONE}`] = () => {
      routes["GET /api/workspaces/w1"] = role("member");
      return fail(403, "permission_denied", "No permission.");
    };
    await show();
    type(/Agent name/, "Helper");
    fireEvent.click(button("Delete permanently"));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull());
    expect(screen.getByRole("alert")).toHaveTextContent("No permission.");
  });
});

describe("form", () => {
  const create = async () => {
    render(<NewAgent workspaceId="w1" />);
    await screen.findByLabelText(/Name/);
  };
  const edit = async () => {
    render(<EditAgent workspaceId="w1" agentId="a1" />);
    await screen.findByLabelText(/Name/);
  };

  it("creates once and opens the new agent", async () => {
    routes[`POST ${LIST}`] = () => Response.json({ ...agent, id: "a9" }, { status: 201 });
    await create();
    type(/Name/, "Helper");
    type(/Instructions/, "Be kind.");
    submit();
    submit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/workspaces/w1/agents/a9"));
    expect(sent("POST")).toHaveLength(1);
    expect(JSON.parse(sent("POST")[0][1]!.body as string)).toEqual({
      name: "Helper",
      purpose: "",
      description: "",
      instructions: "Be kind.",
    });
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it("names what is missing and focuses the first", async () => {
    await create();
    type(/Instructions/, "  \n");
    submit();
    expect(await screen.findByText("Name is required.")).toBeInTheDocument();
    expect(screen.getByText("Instructions are required.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Name/)).toHaveFocus();
    expect(screen.getByLabelText(/Name/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(/Name/)).toHaveAccessibleDescription("Name is required.");
    expect(sent("POST")).toHaveLength(0);
  });

  it("counts instructions live, as the server does, and blocks one too many", async () => {
    routes[`POST ${LIST}`] = () => Response.json(agent, { status: 201 });
    await create();
    expect(screen.getByText("0 / 10,000")).toBeInTheDocument();
    type(/Name/, "Helper");
    type(/Instructions/, "😀".repeat(10_001));
    expect(screen.getByText("10,001 / 10,000")).toBeInTheDocument();
    expect(screen.getByText(/Over the limit/)).toBeInTheDocument();
    submit();
    expect(await screen.findByText(/at most 10,000 characters/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Instructions/)).toHaveFocus();
    expect(sent("POST")).toHaveLength(0);
    type(/Instructions/, "😀".repeat(10_000));
    expect(screen.getByText("10,000 / 10,000")).toBeInTheDocument();
    expect(screen.queryByText(/Over the limit/)).toBeNull();
    submit();
    await waitFor(() => expect(sent("POST")).toHaveLength(1));
  });

  it("shows the server's field errors beside the field", async () => {
    routes[`POST ${LIST}`] = () =>
      fail(422, "validation_error", "Some fields are invalid.", [
        { loc: ["body", "name"], msg: "Name contains invalid characters." },
      ]);
    await create();
    type(/Name/, "x");
    type(/Instructions/, "Be kind.");
    submit();
    expect(await screen.findByText("Name contains invalid characters.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Name/)).toHaveFocus();
    expect(screen.getByLabelText(/Instructions/)).toHaveValue("Be kind.");
  });

  it.each([
    [() => fail(409, "agent_limit", "A workspace can have at most 50 agents."), /at most 50/],
    [() => fail(503, "busy", "The workspace is busy."), /busy/],
    [() => fail(429, "rate_limited", "Too many requests."), /Too many/],
    [() => fail(401, "authentication_required", "x"), /signed out. Nothing was saved/],
    [() => fail(404, "not_found", "x"), /Not saved: this no longer exists/],
    [down, /may have been made: look in My Agents/],
  ])("keeps the text after a failure (%#)", async (response, text) => {
    routes[`POST ${LIST}`] = response;
    await create();
    type(/Name/, "Helper");
    type(/Instructions/, "Long text");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.getByLabelText(/Instructions/)).toHaveValue("Long text");
    expect(router.replace).not.toHaveBeenCalled();
    expect(button("Create agent")).toHaveAttribute("aria-disabled", "false");
  });

  it("saves from the version it opened and shows the agent", async () => {
    routes[`PATCH ${ONE}`] = () => Response.json({ ...agent, version: 4 });
    await edit();
    type(/Description/, "New");
    submit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/workspaces/w1/agents/a1"));
    expect(JSON.parse(sent("PATCH")[0][1]!.body as string)).toEqual({
      version: 3,
      name: "Helper",
      purpose: "Help people",
      description: "New",
      instructions: "Be kind.",
    });
  });

  it("keeps the text when someone else saved first, and loads theirs only after asking", async () => {
    routes[`PATCH ${ONE}`] = () => fail(409, "version_conflict", "This agent has changed.");
    await edit();
    type(/Instructions/, "Mine");
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("This agent has changed.");
    expect(screen.getByLabelText(/Instructions/)).toHaveValue("Mine");
    expect(screen.getByRole("link", { name: /Open the latest/ })).toHaveAttribute("target", "_blank");

    routes[`GET ${ONE}`] = () => Response.json({ ...agent, version: 4, instructions: "Theirs" });
    confirmMock.mockReturnValue(false);
    fireEvent.click(button("Discard my text and load the latest"));
    expect(screen.getByLabelText(/Instructions/)).toHaveValue("Mine");
    confirmMock.mockReturnValue(true);
    fireEvent.click(button("Discard my text and load the latest"));
    expect(await screen.findByDisplayValue("Theirs")).toBeInTheDocument();
    submit();
    await waitFor(() => expect(sent("PATCH")).toHaveLength(2));
    expect(JSON.parse(sent("PATCH")[1][1]!.body as string).version).toBe(4);
  });

  it("does not offer to edit an archived agent", async () => {
    routes[`GET ${ONE}`] = () => Response.json({ ...agent, status: "archived" });
    render(<EditAgent workspaceId="w1" agentId="a1" />);
    expect(await screen.findByText(/Restore it first/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("unsaved text", () => {
  const inShell = async () => {
    routes["GET /api/auth/me"] = () => Response.json({ id: "u1", email: "a@example.com" });
    routes["GET /api/workspaces"] = () =>
      Response.json([{ id: "w1", name: "Team", role: "owner" }]);
    routes["POST /api/auth/logout"] = () => new Response(null, { status: 204 });
    render(
      <AppShell>
        <NewAgent workspaceId="w1" />
      </AppShell>,
    );
    await screen.findByLabelText(/Name/);
  };
  const unloads = () =>
    fireEvent(window, new Event("beforeunload", { cancelable: true })) === false;
  /** Whether the click got through to the link. */
  const clicks = (name: string, init?: MouseEventInit) => {
    let reached = false;
    const stop = (event: Event) => {
      reached = !event.defaultPrevented;
      event.preventDefault(); // jsdom cannot navigate
    };
    const link = screen.getByRole("link", { name });
    link.addEventListener("click", stop);
    fireEvent.click(link, init);
    link.removeEventListener("click", stop);
    return reached;
  };

  it("never asks about a form that is unchanged or changed back", async () => {
    await inShell();
    expect(unloads()).toBe(false);
    expect(clicks("Cancel")).toBe(true);
    type(/Name/, "x");
    expect(unloads()).toBe(true);
    type(/Name/, "");
    expect(unloads()).toBe(false);
    expect(clicks("Dashboard")).toBe(true);
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it.each(["Cancel", "Dashboard", "My Agents"])("asks before following %s", async (name) => {
    await inShell();
    type(/Instructions/, "Long text");
    confirmMock.mockReturnValue(false);
    expect(clicks(name)).toBe(false);
    expect(screen.getByLabelText(/Instructions/)).toHaveValue("Long text");
    confirmMock.mockReturnValue(true);
    expect(clicks(name)).toBe(true);
    expect(confirmMock).toHaveBeenCalledTimes(2);
  });

  it("does not ask when a link opens elsewhere or stays on the page", async () => {
    await inShell();
    type(/Name/, "x");
    expect(clicks("Cancel", { ctrlKey: true })).toBe(true);
    expect(clicks("Skip to content")).toBe(true);
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it("asks before signing out", async () => {
    await inShell();
    type(/Name/, "x");
    confirmMock.mockReturnValue(false);
    fireEvent.click(button("Sign out"));
    await settle();
    expect(sent("POST")).toHaveLength(0);
    confirmMock.mockReturnValue(true);
    fireEvent.click(button("Sign out"));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(unloads()).toBe(false);
  });

  it("asks before the redirect after the session has ended elsewhere", async () => {
    await inShell();
    type(/Instructions/, "Long text");
    routes["GET /api/auth/me"] = () => fail(401, "authentication_required", "x");
    confirmMock.mockReturnValue(false);
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/Instructions/)).toHaveValue("Long text");
    confirmMock.mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });

  it("asks before Back, staying or leaving as told", async () => {
    await inShell();
    const before = history.length;
    const reachedRouter = vi.fn();
    window.addEventListener("popstate", reachedRouter);
    for (const value of ["x", "", "y", "", "z"]) type(/Name/, value);
    expect(history.length).toBe(before + 1);
    confirmMock.mockReturnValue(false);
    history.back();
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(reachedRouter).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/Name/)).toHaveValue("z");
    confirmMock.mockReturnValue(true);
    const back = vi.spyOn(history, "back");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(back).toHaveBeenCalledTimes(1);
    back.mockRestore();
    window.removeEventListener("popstate", reachedRouter);
  });
});
