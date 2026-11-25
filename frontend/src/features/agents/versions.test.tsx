import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentView } from "./AgentView";
import { VersionHistory } from "./VersionHistory";
import { VersionView } from "./VersionView";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/workspaces/w1/agents/a1/versions",
  useParams: () => ({ id: "w1" }),
}));

const ONE = "/api/workspaces/w1/agents/a1";
const LIST = `${ONE}/versions`;
const OLD = `${LIST}/v2`;
const agent = {
  id: "a1",
  status: "active",
  version: 3,
  name: "Helper",
  purpose: null,
  description: null,
  instructions: "Now.",
};
const entry = (number: number, more = {}) => ({
  id: `v${number}`,
  number,
  name: "Helper",
  is_current: number === 3,
  restored_from: null as number | null,
  changed: ["instructions"] as string[] | null,
  saved_by: "ann@example.com" as string | null,
  created_at: "2026-11-24T10:00:00Z",
  ...more,
});
const version = {
  ...entry(2),
  purpose: "Old purpose",
  description: null as string | null,
  instructions: "Then.",
  model: null,
};

let routes: Record<string, () => Response | Promise<Response>>;
const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
  routes[`${init?.method ?? "GET"} ${url}`](),
);
const confirmMock = vi.fn<(text?: string) => boolean>(() => true);
const fail = (status: number, code: string, message = "x") =>
  Response.json({ error: { code, message } }, { status });
const down = () => Promise.reject(new TypeError("down"));
const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
const page = (items: unknown[], next_before: number | null = null) =>
  Response.json({ items, next_before });
const button = (name: string) => screen.getByRole("button", { name });
const ROLL_BACK = "Roll back to version 2";

async function showVersion() {
  const view = render(<VersionView workspaceId="w1" agentId="a1" versionId="v2" />);
  await screen.findByRole("heading", { level: 1, name: "Version 2 of Helper" });
  return view;
}

async function showHistory() {
  const view = render(<VersionHistory workspaceId="w1" agentId="a1" />);
  await screen.findByRole("heading", { level: 1, name: "Version history of Helper" });
  return view;
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("confirm", confirmMock);
  routes = {
    "GET /api/workspaces/w1": () => Response.json({ id: "w1", name: "Team", role: "member" }),
    [`GET ${ONE}`]: () => Response.json(agent),
    [`GET ${LIST}`]: () =>
      page([
        entry(3, { changed: ["name", "instructions"], restored_from: 1 }),
        entry(2, { saved_by: null }),
        entry(1, { changed: null }),
      ]),
    [`GET ${OLD}`]: () => Response.json(version),
    [`POST ${OLD}/rollback`]: () => Response.json({ ...agent, version: 4 }),
  };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockClear();
  confirmMock.mockReset().mockReturnValue(true);
  router.replace.mockReset();
  router.push.mockReset();
});

describe("VersionHistory", () => {
  it("shows what changed, who saved it and which one is current", async () => {
    await showHistory();
    const [three, two, one] = screen.getAllByRole("listitem");
    expect(three).toHaveTextContent("Version 3 (current)");
    expect(three).toHaveTextContent("Restored from version 1. Changed: name, instructions");
    expect(three).toHaveTextContent("Saved by ann@example.com,");
    expect(two).not.toHaveTextContent("(current)");
    expect(two).toHaveTextContent("Changed: instructions");
    expect(two).toHaveTextContent("Saved by Former member,");
    expect(one).toHaveTextContent("Created");
    expect(screen.getByRole("link", { name: "Version 2" })).toHaveAttribute(
      "href",
      "/workspaces/w1/agents/a1/versions/v2",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("loads older versions after those shown", async () => {
    routes[`GET ${LIST}`] = () => page([entry(3)], 3);
    routes[`GET ${LIST}?before=3`] = () => page([entry(2), entry(1, { changed: null })]);
    await showHistory();
    fireEvent.click(button("Show older versions"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(3));
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps what is shown when loading older versions fails, and can retry", async () => {
    routes[`GET ${LIST}`] = () => page([entry(3)], 3);
    routes[`GET ${LIST}?before=3`] = down;
    await showHistory();
    fireEvent.click(button("Show older versions"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    routes[`GET ${LIST}?before=3`] = () => page([entry(2)]);
    fireEvent.click(button("Show older versions"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([404, 422])("is not found when the agent is not (%i)", async (status) => {
    routes[`GET ${ONE}`] = routes[`GET ${LIST}`] = () => fail(status, "x");
    render(<VersionHistory workspaceId="w1" agentId="a1" />);
    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
  });

  it("offers a retry when loading fails", async () => {
    const ready = routes[`GET ${LIST}`];
    routes[`GET ${LIST}`] = down;
    render(<VersionHistory workspaceId="w1" agentId="a1" />);
    const retry = await screen.findByRole("button", { name: /Retry|Try again/ });
    routes[`GET ${LIST}`] = ready;
    fireEvent.click(retry);
    expect(await screen.findAllByRole("listitem")).toHaveLength(3);
  });

  it("goes to sign in when signed out", async () => {
    routes[`GET ${LIST}`] = () => fail(401, "authentication_required");
    render(<VersionHistory workspaceId="w1" agentId="a1" />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });
});

describe("VersionView", () => {
  it("shows the whole configuration of that version", async () => {
    await showVersion();
    for (const text of ["Old purpose", "Then.", "Not set"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.queryByText("Now.")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("says what it was restored from", async () => {
    routes[`GET ${OLD}`] = () => Response.json({ ...version, restored_from: 1, saved_by: null });
    await showVersion();
    expect(screen.getByText("Restored from version 1.")).toBeInTheDocument();
    expect(screen.getByText(/Saved by Former member/)).toBeInTheDocument();
  });

  it("asks, sends the version seen as current, and opens the agent", async () => {
    await showVersion();
    fireEvent.click(button(ROLL_BACK));
    fireEvent.click(button(ROLL_BACK));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/workspaces/w1/agents/a1"),
    );
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(confirmMock.mock.calls[0][0]).toContain("version 2");
    expect(posts()).toHaveLength(1);
    expect(JSON.parse(posts()[0][1]!.body as string)).toEqual({ version: 3 });
  });

  it("does nothing when not confirmed", async () => {
    confirmMock.mockReturnValue(false);
    await showVersion();
    fireEvent.click(button(ROLL_BACK));
    expect(posts()).toHaveLength(0);
    expect(router.push).not.toHaveBeenCalled();
  });

  it("does not offer it for the current version", async () => {
    routes[`GET ${ONE}`] = () => Response.json({ ...agent, version: 2 });
    await showVersion();
    expect(screen.getByText("This is the current version.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("does not offer it for an archived agent", async () => {
    routes[`GET ${ONE}`] = () => Response.json({ ...agent, status: "archived" });
    await showVersion();
    expect(screen.getByText(/archived agent cannot be rolled back/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says when nothing changed", async () => {
    routes[`POST ${OLD}/rollback`] = () => Response.json(agent);
    await showVersion();
    fireEvent.click(button(ROLL_BACK));
    expect(await screen.findByText(/Nothing changed/)).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("a stale page is not sent again until the latest is loaded", async () => {
    routes[`POST ${OLD}/rollback`] = () => fail(409, "version_conflict", "It has changed.");
    await showVersion();
    routes[`GET ${ONE}`] = () => Response.json({ ...agent, version: 7 });
    fireEvent.click(button(ROLL_BACK));
    expect(await screen.findByRole("alert")).toHaveTextContent("It has changed.");
    expect(screen.getByText(/The current version is 3/)).toBeInTheDocument();
    fireEvent.click(button("Load the latest"));
    expect(await screen.findByText(/The current version is 7/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(button(ROLL_BACK));
    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(JSON.parse(posts()[1][1]!.body as string)).toEqual({ version: 7 });
  });

  it("a busy workspace offers the latest state", async () => {
    routes[`POST ${OLD}/rollback`] = () => fail(503, "busy", "Nothing was changed.");
    await showVersion();
    routes[`GET ${ONE}`] = () => Response.json({ ...agent, version: 7 });
    fireEvent.click(button(ROLL_BACK));
    fireEvent.click(await screen.findByRole("button", { name: "Load the latest" }));
    expect(await screen.findByText(/The current version is 7/)).toBeInTheDocument();
  });

  it("shows the real status when the agent was archived meanwhile", async () => {
    routes[`POST ${OLD}/rollback`] = () => {
      routes[`GET ${ONE}`] = () => Response.json({ ...agent, status: "archived" });
      return fail(409, "agent_archived", "This agent is archived.");
    };
    await showVersion();
    fireEvent.click(button(ROLL_BACK));
    expect(await screen.findByText(/cannot be rolled back/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("This agent is archived.");
    expect(screen.queryByRole("button", { name: "Load the latest" })).toBeNull();
  });

  it.each([
    [() => fail(503, "busy", "Nothing was changed."), /Nothing was changed/, false],
    [() => fail(409, "version_limit", "Duplicate the agent."), /Duplicate the agent/, false],
    [() => fail(409, "version_invalid", "No longer meets."), /No longer meets/, false],
    [() => fail(429, "rate_limited", "Too many requests."), /Too many/, false],
    [down, /Could not reach the server/, true],
    [() => fail(500, "internal_error", "Went wrong."), /Went wrong/, true],
  ])("explains a failure and never claims more than it knows (%#)", async (answer, text, unknown) => {
    routes[`POST ${OLD}/rollback`] = answer;
    await showVersion();
    fireEvent.click(button(ROLL_BACK));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(text);
    expect(/may have been made/.test(alert.textContent!)).toBe(unknown);
    expect(router.push).not.toHaveBeenCalled();
  });

  it("shows not found when the agent has gone meanwhile", async () => {
    routes[`POST ${OLD}/rollback`] = () => {
      routes[`GET ${ONE}`] = () => fail(404, "not_found");
      return fail(404, "not_found");
    };
    await showVersion();
    fireEvent.click(button(ROLL_BACK));
    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
  });

  it("goes to sign in when signed out", async () => {
    routes[`POST ${OLD}/rollback`] = () => fail(401, "authentication_required");
    await showVersion();
    fireEvent.click(button(ROLL_BACK));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });

  it.each([404, 422])("a version of another agent is not found (%i)", async (status) => {
    routes[`GET ${OLD}`] = () => fail(status, "x");
    render(<VersionView workspaceId="w1" agentId="a1" versionId="v2" />);
    expect(await screen.findByText("Version not found")).toBeInTheDocument();
  });

  it("cannot be steered to another endpoint by the id", async () => {
    routes[`GET ${LIST}/..%2F..%2Fx`] = () => fail(404, "x");
    render(<VersionView workspaceId="w1" agentId="a1" versionId="../../x" />);
    expect(await screen.findByText("Version not found")).toBeInTheDocument();
  });
});

describe("plain text", () => {
  const evil = "<img src=x onerror=alert(1)><script>window.hit=1</script>";

  it("shows markup literally in the history and in a version", async () => {
    routes[`GET ${LIST}`] = () => page([entry(3, { name: evil, saved_by: `${evil}@x.y` })]);
    const list = await showHistory();
    expect(screen.getByText(evil)).toBeInTheDocument();
    expect(list.container.querySelector("img, script")).toBeNull();
    cleanup();
    routes[`GET ${OLD}`] = () =>
      Response.json({ ...version, name: evil, purpose: evil, instructions: evil });
    const one = await showVersion();
    expect(screen.getAllByText(evil)).toHaveLength(3);
    expect(one.container.querySelector("img, script")).toBeNull();
  });
});

describe("AgentView", () => {
  it.each(["active", "archived"])("links to the history of an agent that is %s", async (status) => {
    routes[`GET ${ONE}`] = () => Response.json({ ...agent, status });
    render(<AgentView workspaceId="w1" agentId="a1" />);
    expect(await screen.findByRole("link", { name: "Version history" })).toHaveAttribute(
      "href",
      "/workspaces/w1/agents/a1/versions",
    );
    expect(screen.getByText("Version 3.", { exact: false })).toBeInTheDocument();
  });
});
