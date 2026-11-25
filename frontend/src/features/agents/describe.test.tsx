import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearUnsaved } from "@/lib/unsavedChanges";

import { DescribeAgent } from "./DescribeAgent";
import { NewAgent } from "./NewAgent";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const BUILDER = "/api/workspaces/w1/agent-builder";
const DRAFTS = `POST ${BUILDER}/drafts?disclosure=none`;
const CREATE = "POST /api/workspaces/w1/agents";
const draft = {
  name: "Order helper",
  purpose: "Help with orders",
  description: "",
  instructions: "Be kind.",
};
let routes: Record<string, () => Response | Promise<Response>>;
const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
  routes[`${init?.method ?? "GET"} ${url}`](),
);
const confirmMock = vi.fn(() => true);

const fail = (status: number, code: string, message: string, details?: unknown) =>
  Response.json({ error: { code, message, details } }, { status });
const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
const type = (label: RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const questions = () => screen.getByRole("form", { name: "Questions" });
const generate = () => fireEvent.submit(questions());
const create = () => fireEvent.submit(document.querySelectorAll("form")[1]);
const unloads = () =>
  fireEvent(window, new Event("beforeunload", { cancelable: true })) === false;
const reviewing = () => screen.findByRole("heading", { name: "Review the draft" });

const open = async () => {
  render(<DescribeAgent workspaceId="w1" />);
  await screen.findByLabelText(/What is the agent for/);
};
const answer = () => {
  type(/What is the agent for/, "Orders");
  type(/What should it do/, "Reply");
};
const openWithDraft = async () => {
  await open();
  answer();
  generate();
  await reviewing();
};

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("confirm", confirmMock);
  routes = {
    "GET /api/workspaces/w1": () => Response.json({ id: "w1", name: "Team", role: "owner" }),
    "GET /api/workspaces/w1/members": () => Response.json([]),
    [`GET ${BUILDER}`]: () => Response.json({ available: true, disclosure: "none" }),
    [DRAFTS]: () => Response.json({ draft, sample: true }),
    [CREATE]: () => Response.json({ ...draft, id: "a9" }, { status: 201 }),
  };
});

afterEach(() => {
  cleanup();
  clearUnsaved();
  vi.unstubAllGlobals();
  fetchMock.mockClear();
  confirmMock.mockReset().mockReturnValue(true);
  router.replace.mockReset();
});

describe("offering the builder", () => {
  it("offers it on the manual form when available", async () => {
    render(<NewAgent workspaceId="w1" />);
    expect(await screen.findByRole("link", { name: /Describe your agent/ })).toHaveAttribute(
      "href",
      "/workspaces/w1/agents/new/describe",
    );
  });

  it.each([
    ["not set up", () => Response.json({ available: false, disclosure: "none" })],
    ["unknown", () => Promise.reject(new TypeError("down"))],
  ])("hides it when %s, and the manual form works", async (_, reply) => {
    routes[`GET ${BUILDER}`] = reply;
    render(<NewAgent workspaceId="w1" />);
    await screen.findByLabelText(/Name/);
    expect(screen.queryByRole("link", { name: /Describe/ })).toBeNull();
  });

  it("shows no form on its own page when not set up", async () => {
    routes[`GET ${BUILDER}`] = () => Response.json({ available: false, disclosure: "none" });
    render(<DescribeAgent workspaceId="w1" />);
    expect(await screen.findByText(/not available/)).toBeInTheDocument();
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.getByRole("link", { name: /yourself/ })).toHaveAttribute(
      "href",
      "/workspaces/w1/agents/new",
    );
  });

  it("can retry when that is unknown", async () => {
    routes[`GET ${BUILDER}`] = () => Promise.reject(new TypeError("down"));
    render(<DescribeAgent workspaceId="w1" />);
    const retry = await screen.findByRole("button", { name: "Retry" });
    routes[`GET ${BUILDER}`] = () => Response.json({ available: true, disclosure: "none" });
    fireEvent.click(retry);
    await screen.findByLabelText(/What is the agent for/);
  });

  it("a workspace that is not the person's own is not found", async () => {
    routes["GET /api/workspaces/w1"] = () => fail(404, "not_found", "x");
    render(<DescribeAgent workspaceId="w1" />);
    expect(await screen.findByText("Workspace not found")).toBeInTheDocument();
  });
});

describe("answers", () => {
  it("names what is missing and focuses the first", async () => {
    await open();
    type(/What is the agent for/, "  ");
    generate();
    expect(await screen.findAllByText("Please answer this question.")).toHaveLength(2);
    expect(screen.getByLabelText(/What is the agent for/)).toHaveFocus();
    expect(posts()).toHaveLength(0);
  });

  it("limits each answer, counting as the server does", async () => {
    await open();
    answer();
    type(/tone/, "😀".repeat(1001));
    generate();
    expect(await screen.findByText("Must be at most 1,000 characters.")).toBeInTheDocument();
    expect(posts()).toHaveLength(0);
    type(/tone/, `  ${"😀".repeat(1000)}  `);
    generate();
    await reviewing();
  });

  it("limits all answers together", async () => {
    await open();
    for (const label of [/agent for/, /should it do/, /tone/]) type(label, "x".repeat(1000));
    expect(screen.getByText("All answers: 3,000 / 3,000")).toBeInTheDocument();
    type(/Anything else/, "x");
    expect(screen.getByText(/Over the limit/)).toBeInTheDocument();
    generate();
    expect(posts()).toHaveLength(0);
    type(/Anything else/, " ");
    generate();
    await reviewing();
  });

  it("shows the server's errors beside the answer", async () => {
    routes[DRAFTS] = () =>
      fail(422, "validation_error", "x", [{ loc: ["body", "tone"], msg: "Bad tone." }]);
    await open();
    answer();
    generate();
    expect(await screen.findByText("Bad tone.")).toBeInTheDocument();
    expect(screen.getByLabelText(/tone/)).toHaveFocus();
  });

  it.each([
    [502, "draft_invalid", "The AI returned a draft that cannot be used."],
    [504, "provider_timeout", "The AI provider took too long to answer."],
    [503, "provider_rate_limited", "The AI provider is receiving too many requests."],
    [429, "rate_limited", "Too many drafts."],
    [409, "agent_limit", "A workspace can have at most 50 agents."],
    [401, "authentication_required", "You are signed out."],
  ])("keeps the answers after %s %s, without retrying", async (status, code, message) => {
    routes[DRAFTS] = () => fail(status, code, message);
    await open();
    answer();
    generate();
    const alert = await screen.findByText(new RegExp(message.replace(".", "\\.")));
    expect(alert).toHaveTextContent("No agent was created. Your answers are still here.");
    expect(screen.getByLabelText(/What is the agent for/)).toHaveValue("Orders");
    expect(screen.queryByRole("heading", { name: "Review the draft" })).toBeNull();
    expect(posts()).toHaveLength(1);
    routes[DRAFTS] = () => Response.json({ draft, sample: false });
    generate();
    await reviewing();
    expect(screen.queryByText(/No agent was created/)).toBeNull();
  });
});

describe("draft", () => {
  it("fills the form, saves nothing, and takes focus", async () => {
    await openWithDraft();
    expect(screen.getByRole("heading", { name: "Review the draft" })).toHaveFocus();
    expect(screen.getByText(/Nothing is saved yet/)).toBeInTheDocument();
    expect(screen.getByText(/Sample draft, made without AI/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toHaveValue("Order helper");
    expect(screen.getByLabelText(/^Instructions/)).toHaveValue("Be kind.");
    expect(posts().map(([url]) => url)).toEqual([`${BUILDER}/drafts?disclosure=none`]);
    expect(JSON.parse(posts()[0][1]!.body as string)).toEqual({
      purpose: "Orders",
      tasks: "Reply",
      tone: "",
      constraints: "",
      extra: "",
    });
  });

  it("a draft that is not from the mock is not called a sample", async () => {
    routes[DRAFTS] = () => Response.json({ draft, sample: false });
    await openWithDraft();
    expect(screen.queryByText(/Sample draft/)).toBeNull();
  });

  it("saves what the person edited, and only the four fields", async () => {
    routes[DRAFTS] = () =>
      Response.json({ draft: { ...draft, tools: ["x"], model: "m" }, sample: true });
    await openWithDraft();
    type(/^Name/, "Mine");
    create();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/workspaces/w1/agents/a9"));
    expect(JSON.parse(posts()[1][1]!.body as string)).toEqual({ ...draft, name: "Mine" });
    expect(unloads()).toBe(false);
  });

  it("renders markup literally", async () => {
    const evil = "<script>window.hit=1</script><img src=x onerror=alert(1)>";
    routes[DRAFTS] = () =>
      Response.json({
        draft: { name: evil, purpose: evil, description: evil, instructions: evil },
        sample: true,
      });
    await openWithDraft();
    expect(screen.getByLabelText(/^Instructions/)).toHaveValue(evil);
    expect(document.querySelector("script, img")).toBeNull();
  });

  it("asks before replacing an edited draft only", async () => {
    await openWithDraft();
    routes[DRAFTS] = () => Response.json({ draft: { ...draft, name: "Second" }, sample: true });
    generate();
    await waitFor(() => expect(screen.getByLabelText(/^Name/)).toHaveValue("Second"));
    expect(confirmMock).not.toHaveBeenCalled();
    type(/^Name/, "Mine");
    confirmMock.mockReturnValue(false);
    generate();
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(posts()).toHaveLength(2);
    expect(screen.getByLabelText(/^Name/)).toHaveValue("Mine");
    confirmMock.mockReturnValue(true);
    routes[DRAFTS] = () => Response.json({ draft: { ...draft, name: "Third" }, sample: true });
    generate();
    await waitFor(() => expect(screen.getByLabelText(/^Name/)).toHaveValue("Third"));
  });

  it("keeps an edited draft when replacing it fails", async () => {
    await openWithDraft();
    type(/^Name/, "Mine");
    routes[DRAFTS] = () => fail(504, "provider_timeout", "Too slow.");
    generate();
    await screen.findByText(/Too slow/);
    expect(screen.getByLabelText(/^Name/)).toHaveValue("Mine");
    expect(screen.getByLabelText(/^Name/)).not.toHaveAttribute("readonly");
  });

  it("cannot be edited or saved while it is being replaced", async () => {
    await openWithDraft();
    let answerNow!: (response: Response) => void;
    routes[DRAFTS] = () => new Promise<Response>((resolve) => (answerNow = resolve));
    generate();
    generate();
    await waitFor(() => expect(screen.getByLabelText(/^Name/)).toHaveAttribute("readonly"));
    create();
    expect(posts()).toHaveLength(2); // the first draft and one replacement
    answerNow(Response.json({ draft, sample: true }));
    await waitFor(() => expect(screen.getByLabelText(/^Name/)).not.toHaveAttribute("readonly"));
  });

  it("cannot be replaced while it is being saved", async () => {
    await openWithDraft();
    routes[CREATE] = () => new Promise<Response>(() => {});
    create();
    await screen.findByText("Saving…");
    generate();
    expect(posts()).toHaveLength(2);
  });

  it("a failed save keeps the draft", async () => {
    await openWithDraft();
    routes[CREATE] = () => fail(409, "agent_limit", "Full.");
    create();
    const section = await screen.findByRole("region", { name: "Review the draft" });
    expect(await within(section).findByText(/Full\./)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toHaveValue("Order helper");
    expect(unloads()).toBe(true);
  });
});

describe("unsaved text", () => {
  it("asks about answers, and about a draft nobody edited", async () => {
    await open();
    expect(unloads()).toBe(false);
    type(/tone/, "x");
    expect(unloads()).toBe(true);
    type(/tone/, "");
    expect(unloads()).toBe(false);
    answer();
    generate();
    await reviewing();
    type(/What is the agent for/, "");
    type(/What should it do/, "");
    expect(unloads()).toBe(true);
    type(/^Name/, "Mine");
    type(/^Name/, "Order helper");
    expect(unloads()).toBe(true); // unchanged again, still unsaved
  });

  it("asks once per way of leaving", async () => {
    await openWithDraft();
    const before = history.length;
    type(/^Name/, "Mine");
    expect(history.length).toBe(before);
    confirmMock.mockReturnValue(false);
    const link = screen.getByRole("link", { name: "Cancel" });
    expect(fireEvent.click(link)).toBe(false);
    expect(confirmMock).toHaveBeenCalledTimes(1);
  });
});

describe("who receives the answers", () => {
  const free =
    "Your answers are sent to Google Gemini. Google may use them to improve its products and people may read them. Don't include personal or confidential information.";
  const paid =
    "Your answers are sent to Google Gemini. Don't include personal or confidential information.";
  const serve = (disclosure: unknown) => {
    routes[`GET ${BUILDER}`] = () => Response.json({ available: true, disclosure });
  };

  it.each([
    ["none", ""],
    ["gemini_free", free],
    ["gemini_paid", paid],
  ])("says so for %s before the questions, and sends what it said", async (disclosure, text) => {
    serve(disclosure);
    routes[`POST ${BUILDER}/drafts?disclosure=${disclosure}`] = routes[DRAFTS];
    await open();
    const notice = screen.getByRole("note");
    expect(notice).toHaveTextContent(text, { normalizeWhitespace: false });
    expect(notice.textContent).toBe(text);
    const first = screen.getByLabelText(/What is the agent for/);
    expect(notice.compareDocumentPosition(first)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(first).toHaveAttribute("aria-describedby", "answers-notice");
    answer();
    generate();
    await reviewing();
  });

  it.each([undefined, null, "", "openai", "constructor", 5])(
    "lets nobody type when it is %s",
    async (disclosure) => {
      serve(disclosure);
      render(<DescribeAgent workspaceId="w1" />);
      await screen.findByRole("button", { name: "Retry" });
      expect(screen.queryByRole("textbox")).toBeNull();
      serve("gemini_free");
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      expect(await screen.findByRole("note")).toHaveTextContent(free);
    },
  );

  it("shows a changed notice, keeps the answers, and sends only when asked again", async () => {
    routes[DRAFTS] = () => fail(409, "disclosure_changed", "Not sent.");
    await open();
    answer();
    serve("gemini_free");
    generate();
    await waitFor(() => expect(screen.getByRole("note")).toHaveTextContent(free));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not sent.");
    expect(screen.getByLabelText(/What is the agent for/)).toHaveValue("Orders");
    expect(posts()).toHaveLength(1);
    routes[`POST ${BUILDER}/drafts?disclosure=gemini_free`] = () =>
      Response.json({ draft, sample: false });
    generate();
    await reviewing();
    expect(posts()).toHaveLength(2);
  });

  it.each([
    ["drafts are switched off", { available: false, disclosure: "none" }],
    ["the new notice is unknown", { available: true, disclosure: "something new" }],
  ])("keeps the answers, and lets nobody type, when %s", async (_, status) => {
    routes[DRAFTS] = () => fail(409, "disclosure_changed", "Not sent.");
    await open();
    answer();
    routes[`GET ${BUILDER}`] = () => Response.json(status);
    generate();
    await screen.findByRole("button", { name: "Retry" });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const first = await screen.findByLabelText(/What is the agent for/);
    expect(first).toHaveValue("Orders");
    expect(first).toHaveAttribute("readonly");
    generate();
    expect(posts()).toHaveLength(1);
    serve("gemini_free");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("note")).toHaveTextContent(free));
    expect(first).toHaveValue("Orders");
    expect(first).not.toHaveAttribute("readonly");
  });

  it("keeps the answers when the new notice cannot be loaded", async () => {
    routes[DRAFTS] = () => fail(409, "disclosure_changed", "Not sent.");
    await open();
    answer();
    routes[`GET ${BUILDER}`] = () => Promise.reject(new TypeError("down"));
    generate();
    expect(await screen.findByRole("alert")).toHaveTextContent("Not sent.");
    expect(screen.getByLabelText(/What is the agent for/)).toHaveValue("Orders");
  });
});
