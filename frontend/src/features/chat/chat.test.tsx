import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentView } from "@/features/agents/AgentView";
import { WorkspaceSettings } from "@/features/workspaces/WorkspaceSettings";

import { ChatList } from "./ChatList";
import { ChatView } from "./ChatView";
import { parseEvents } from "./stream";
import type { ChatMessage } from "./types";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/workspaces/w1/agents/a1/conversations/c1",
  useParams: () => ({ id: "w1" }),
}));

const AGENT = "/api/workspaces/w1/agents/a1";
const CHATS = `${AGENT}/conversations`;
const CHAT = `${CHATS}/c1`;
const STREAM = `${CHAT}/messages/stream`;
const agent = {
  id: "a1",
  status: "active",
  version: 2,
  name: "Helper",
  purpose: null,
  description: null,
  instructions: "Be kind.",
};
const message = (sequence: number, role: "user" | "assistant", content: string): ChatMessage => ({
  id: `m${sequence}`,
  sequence,
  role,
  content,
  agent_version: role === "assistant" ? 2 : null,
  request_id: role === "user" ? `r${sequence}` : null,
  created_at: "2026-11-26T10:00:00Z",
});

let routes: Record<string, (init?: RequestInit) => Response | Promise<Response>>;
const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  const key = `${init?.method ?? "GET"} ${url.split("?")[0]}`;
  const route = routes[key] ?? routes[`${init?.method ?? "GET"} ${url}`];
  if (!route) throw new Error(`no route for ${key}`);
  return route(init);
});
const confirmMock = vi.fn(() => true);

const fail = (status: number, code: string, text: string) =>
  Response.json({ error: { code, message: text } }, { status });
const page = (items: ChatMessage[], next_before: number | null = null) => () =>
  Response.json({ items, next_before });
const event = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
const streamCalls = () => fetchMock.mock.calls.filter(([url]) => url.startsWith(STREAM));
const sentBody = (n = 0) => JSON.parse(String(streamCalls()[n][1]?.body)) as Record<string, string>;
const button = (name: string | RegExp) => screen.getByRole("button", { name });
const composer = () => screen.getByLabelText("Message") as HTMLTextAreaElement;

/** A response whose events arrive one by one, when `push` is called; `end` closes it. */
function live() {
  const encoder = new TextEncoder();
  let control!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      control = c;
    },
  });
  return {
    response: (init?: RequestInit) => {
      init?.signal?.addEventListener("abort", () => {
        try {
          control.error(new DOMException("Aborted", "AbortError"));
        } catch {
          // already closed
        }
      });
      return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
    },
    push: (text: string) => control.enqueue(encoder.encode(text)),
    end: () => control.close(),
  };
}

function type(text: string) {
  fireEvent.change(composer(), { target: { value: text } });
}

function view() {
  return render(<ChatView workspaceId="w1" agentId="a1" conversationId="c1" />);
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("confirm", confirmMock);
  routes = {
    "GET /api/workspaces/w1": () => Response.json({ id: "w1", name: "Team", role: "owner" }),
    [`GET ${AGENT}`]: () => Response.json(agent),
    "GET /api/workspaces/w1/agent-builder": () =>
      Response.json({ available: true, disclosure: "none" }),
    [`GET ${CHAT}/messages`]: page([]),
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

describe("events", () => {
  it("are split at blank lines, also across chunks", () => {
    const text = event("piece", { text: "a\n\nb" }) + event("done", { message: 1, answer: 2 });
    const first = parseEvents(text.slice(0, 10));
    expect(first.events).toEqual([]);
    const all = parseEvents(first.rest + text.slice(10));
    expect(all.events).toEqual([
      { type: "piece", text: "a\n\nb" },
      { type: "done", answer: { message: 1, answer: 2 } },
    ]);
    expect(all.rest).toBe("");
  });
});

describe("plain text", () => {
  const evil = `<script>window.hit=1</script><img src=x onerror="window.hit=1"> **bold** [x](javascript:alert(1))`;

  it("shows stored messages literally", async () => {
    routes[`GET ${CHAT}/messages`] = page([message(1, "user", evil), message(2, "assistant", evil)]);
    const { container } = view();
    expect(await screen.findAllByText(evil)).toHaveLength(2);
    expect(container.querySelector("script, img, a[href^='javascript'], strong")).toBeNull();
    expect("hit" in window).toBe(false);
  });

  it("shows streamed text literally", async () => {
    const stream = live();
    routes[`POST ${STREAM}`] = stream.response;
    const { container } = view();
    await screen.findByLabelText("Message");
    type("hi");
    fireEvent.click(button("Send"));
    stream.push(event("message", message(1, "user", "hi")));
    stream.push(event("piece", { text: evil }));
    expect(await screen.findByText(evil)).toBeInTheDocument();
    expect(container.querySelector("script, img, a[href^='javascript']")).toBeNull();
    stream.end();
  });
});

describe("chat", () => {
  it("says when there are no messages yet", async () => {
    view();
    expect(screen.getByRole("status")).toHaveTextContent("Loading conversation");
    expect(await screen.findByText(/No messages yet/)).toBeInTheDocument();
    expect(composer()).toBeEnabled();
  });

  it("streams an answer in order and keeps the stored one", async () => {
    const stream = live();
    routes[`POST ${STREAM}`] = stream.response;
    view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.click(button("Send"));
    expect(composer().value).toBe("");
    expect(screen.getByRole("status")).toHaveTextContent("Sending");
    stream.push(event("message", message(1, "user", "Hello")));
    stream.push(event("piece", { text: "Hi " }));
    expect(await screen.findByText("Hi")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("answering");
    stream.push(event("piece", { text: "there" }));
    expect(await screen.findByText("Hi there")).toBeInTheDocument();
    stream.push(
      event("done", { message: message(1, "user", "Hello"), answer: message(2, "assistant", "Hi there") }),
    );
    stream.end();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answer complete."));
    expect(screen.getAllByText("Hi there")).toHaveLength(1);
    expect(screen.getAllByText("Hello")).toHaveLength(1);
    expect(screen.getByText(/version 2/)).toBeInTheDocument();
    const body = sentBody();
    expect(body.content).toBe("Hello");
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(streamCalls()[0][0]).toBe(`${STREAM}?disclosure=none`);
  });

  it("sends once however often it is asked", async () => {
    const stream = live();
    routes[`POST ${STREAM}`] = stream.response;
    view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.click(button("Send"));
    type("Again");
    fireEvent.click(button("Send"));
    fireEvent.keyDown(composer(), { key: "Enter" });
    await settle();
    expect(streamCalls()).toHaveLength(1);
    stream.end();
  });

  it("sends with Enter but not with Shift+Enter", async () => {
    routes[`POST ${STREAM}`] = () => fail(409, "agent_paused", "This agent is paused.");
    view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.keyDown(composer(), { key: "Enter", shiftKey: true });
    await settle();
    expect(streamCalls()).toHaveLength(0);
    fireEvent.keyDown(composer(), { key: "Enter" });
    await waitFor(() => expect(streamCalls()).toHaveLength(1));
  });

  it("stops an answer and offers to try the same message again", async () => {
    const first = live();
    routes[`POST ${STREAM}`] = first.response;
    view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.click(button("Send"));
    first.push(event("message", message(1, "user", "Hello")));
    first.push(event("piece", { text: "Partial" }));
    await screen.findByText("Partial");
    routes[`POST ${CHAT}/messages/stop`] = () => new Response(null, { status: 204 });
    fireEvent.click(button("Stop answering"));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Stopped"));
    expect(streamCalls()[0][1]?.signal?.aborted).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => url === `${CHAT}/messages/stop`)).toBe(true);
    expect(screen.getByText("Incomplete, not saved.")).toBeInTheDocument();
    const second = live();
    routes[`POST ${STREAM}`] = second.response;
    fireEvent.click(button("Retry the last message"));
    expect(sentBody(1)).toEqual(sentBody(0));
    second.end();
  });

  it("puts refused text back and shows why", async () => {
    routes[`POST ${STREAM}`] = () => fail(429, "rate_limited", "You sent too many messages.");
    view();
    await screen.findByLabelText("Message");
    type("Keep me");
    fireEvent.click(button("Send"));
    await waitFor(() => expect(composer().value).toBe("Keep me"));
    expect(screen.getByRole("status")).toHaveTextContent("You sent too many messages.");
    expect(screen.queryByRole("button", { name: "Retry the last message" })).toBeNull();
  });

  it("shows a failed answer with the reason and a retry of the same request", async () => {
    const stream = live();
    routes[`POST ${STREAM}`] = stream.response;
    view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.click(button("Send"));
    stream.push(event("message", message(1, "user", "Hello")));
    stream.push(event("error", { code: "provider_timeout", message: "Took too long." }));
    stream.end();
    expect(await screen.findByRole("alert")).toHaveTextContent("Took too long.");
    expect(screen.getByRole("status")).toHaveTextContent("No answer.");
    routes[`POST ${STREAM}`] = live().response;
    fireEvent.click(button("Retry the last message"));
    expect(sentBody(1)).toEqual(sentBody(0));
  });

  it("says that a broken connection may have saved the answer", async () => {
    const stream = live();
    routes[`POST ${STREAM}`] = stream.response;
    view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.click(button("Send"));
    stream.push(event("message", message(1, "user", "Hello")));
    stream.end();
    expect(await screen.findByRole("alert")).toHaveTextContent("may have been saved");
    expect(button("Retry the last message")).toBeInTheDocument();
  });

  it("offers to repeat an unanswered message after a reload", async () => {
    routes[`GET ${CHAT}/messages`] = page([message(1, "user", "Lost")]);
    routes[`POST ${STREAM}`] = live().response;
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Retry the last message" }));
    expect(sentBody()).toEqual({ request_id: "r1", content: "Lost" });
  });

  it("shows earlier messages on request", async () => {
    routes[`GET ${CHAT}/messages`] = (() => {
      let calls = 0;
      return () => {
        calls += 1;
        return calls === 1
          ? Response.json({ items: [message(3, "user", "new")], next_before: 3 })
          : Response.json({ items: [message(1, "user", "old"), message(2, "assistant", "a")], next_before: null });
      };
    })();
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Show earlier messages" }));
    await screen.findByText("old");
    const items = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items[0]).toContain("old");
    expect(items[2]).toContain("new");
    expect(screen.queryByRole("button", { name: "Show earlier messages" })).toBeNull();
  });

  it.each([
    ["paused", "resumed"],
    ["archived", "restored and resumed"],
  ])("cannot send to a %s agent", async (status, until) => {
    routes[`GET ${AGENT}`] = () => Response.json({ ...agent, status });
    view();
    expect(await screen.findByText(new RegExp(`It cannot answer until it is ${until}`))).toBeInTheDocument();
    expect(composer()).toBeDisabled();
    expect(button("Send")).toBeDisabled();
  });

  it("checks the agent again when the server says it was paused", async () => {
    routes[`POST ${STREAM}`] = () => {
      routes[`GET ${AGENT}`] = () => Response.json({ ...agent, status: "paused" });
      return fail(409, "agent_paused", "This agent is paused.");
    };
    view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.click(button("Send"));
    expect(await screen.findByText(/This agent is paused. It cannot answer/)).toBeInTheDocument();
  });

  it("names who receives the messages before anyone types", async () => {
    routes["GET /api/workspaces/w1/agent-builder"] = () =>
      Response.json({ available: true, disclosure: "gemini_free" });
    routes[`POST ${STREAM}`] = live().response;
    view();
    const notice = await screen.findByText(/sent to Google Gemini/);
    expect(notice).toHaveTextContent("Your messages, the conversation so far and the agent's instructions");
    expect(composer()).toHaveAttribute("aria-describedby", expect.stringContaining(notice.id));
    type("Hello");
    fireEvent.click(button("Send"));
    expect(streamCalls()[0][0]).toBe(`${STREAM}?disclosure=gemini_free`);
  });

  it("asks again when the notice changed, keeping the text", async () => {
    routes[`POST ${STREAM}`] = () => {
      routes["GET /api/workspaces/w1/agent-builder"] = () =>
        Response.json({ available: true, disclosure: "gemini_paid" });
      return fail(409, "disclosure_changed", "Who receives what you type has changed.");
    };
    view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.click(button("Send"));
    expect(await screen.findByText(/sent to Google Gemini/)).toBeInTheDocument();
    expect(composer().value).toBe("Hello");
  });

  it("is off without a provider", async () => {
    routes["GET /api/workspaces/w1/agent-builder"] = () =>
      Response.json({ available: false, disclosure: "none" });
    view();
    expect(await screen.findByText(/no AI provider is set up/)).toBeInTheDocument();
    expect(composer()).toBeDisabled();
  });

  it("shows a load failure with a retry, and a missing conversation", async () => {
    routes[`GET ${CHAT}/messages`] = () => Promise.reject(new TypeError("down"));
    view();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    routes[`GET ${CHAT}/messages`] = () => fail(404, "not_found", "Not found.");
    fireEvent.click(button("Retry"));
    expect(await screen.findByRole("heading", { name: "Conversation not found" })).toBeInTheDocument();
  });

  it("deletes after asking", async () => {
    routes[`DELETE ${CHAT}`] = () => new Response(null, { status: 204 });
    view();
    await screen.findByLabelText("Message");
    confirmMock.mockReturnValueOnce(false);
    fireEvent.click(button("Delete permanently"));
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    fireEvent.click(button("Delete permanently"));
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/workspaces/w1/agents/a1/conversations"),
    );
  });

  it("stops the answer when the page is left", async () => {
    const stream = live();
    routes[`POST ${STREAM}`] = stream.response;
    const { unmount } = view();
    await screen.findByLabelText("Message");
    type("Hello");
    fireEvent.click(button("Send"));
    await waitFor(() => expect(streamCalls()).toHaveLength(1));
    routes[`POST ${CHAT}/messages/stop`] = () => new Response(null, { status: 204 });
    unmount();
    expect(streamCalls()[0][1]?.signal?.aborted).toBe(true);
    const stop = fetchMock.mock.calls.find(([url]) => url === `${CHAT}/messages/stop`);
    expect(stop?.[1]?.keepalive).toBe(true);
  });
});

describe("conversation list", () => {
  const conversation = {
    id: "c1",
    agent_id: "a1",
    message_count: 2,
    created_at: "2026-11-26T10:00:00Z",
    updated_at: "2026-11-26T11:00:00Z",
  };

  it("lists the person's conversations and starts a new one", async () => {
    routes[`GET ${CHATS}`] = () => Response.json({ items: [conversation], total: 1 });
    routes[`POST ${CHATS}`] = () => Response.json({ ...conversation, id: "c2" }, { status: 201 });
    render(<ChatList workspaceId="w1" agentId="a1" />);
    expect(await screen.findByRole("link", { name: /Conversation started/ })).toHaveAttribute(
      "href",
      "/workspaces/w1/agents/a1/conversations/c1",
    );
    expect(screen.getByText(/2 messages/)).toBeInTheDocument();
    expect(screen.getByText(/Only you can see your conversations/)).toBeInTheDocument();
    fireEvent.click(button("New conversation"));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/workspaces/w1/agents/a1/conversations/c2"),
    );
  });

  it("starts none for a paused agent and says when there are none", async () => {
    routes[`GET ${AGENT}`] = () => Response.json({ ...agent, status: "paused" });
    routes[`GET ${CHATS}`] = () => Response.json({ items: [], total: 0 });
    render(<ChatList workspaceId="w1" agentId="a1" />);
    expect(await screen.findByText("No conversations yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New conversation" })).toBeNull();
    expect(screen.getByText(/This agent is paused/)).toBeInTheDocument();
  });
});

describe("owners are warned", () => {
  it("that deleting an agent deletes everyone's conversations", async () => {
    render(<AgentView workspaceId="w1" agentId="a1" />);
    expect(await screen.findByText(/everyone's conversations with it/)).toHaveTextContent(
      "you cannot see what you would delete",
    );
    expect(screen.getByRole("link", { name: "Chat with this agent" })).toHaveAttribute(
      "href",
      "/workspaces/w1/agents/a1/conversations",
    );
  });

  it("that deleting a workspace deletes everyone's conversations", async () => {
    routes["GET /api/workspaces/w1/members"] = () => Response.json([]);
    render(<WorkspaceSettings id="w1" />);
    expect(await screen.findByText(/private conversations with them, which you cannot see/)).toBeInTheDocument();
  });
});
