import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthForm } from "./AuthForm";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => {
  const router = { replace };
  return { useRouter: () => router };
});

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function apiError(status: number, code: string, message: string, details?: unknown): Response {
  return json(status, { error: { code, message, details } });
}

function respond(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function submit(name: string) {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough pw" } });
  fireEvent.click(screen.getByRole("button", { name }));
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  replace.mockReset();
});

describe("AuthForm", () => {
  it("registers with same-origin JSON and opens the dashboard", async () => {
    const fetchMock = respond(json(201, { id: "1", email: "a@example.com" }));
    render(<AuthForm mode="register" />);
    submit("Create account");
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/register");
    expect(init).toMatchObject({ method: "POST", credentials: "same-origin" });
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ email: "a@example.com", password: "long enough pw" });
  });

  it("stores nothing in browser storage after login", async () => {
    respond(json(200, { id: "1", email: "a@example.com" }));
    render(<AuthForm mode="login" />);
    submit("Sign in");
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("shows validation messages on their fields", async () => {
    respond(
      apiError(422, "validation_error", "Some fields are invalid.", [
        { loc: ["body", "email"], msg: "Enter a valid email address." },
        { loc: ["body", "password"], msg: "Password must be 12 to 128 characters." },
      ]),
    );
    render(<AuthForm mode="register" />);
    submit("Create account");
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      "Password must be 12 to 128 characters.",
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it.each([
    [apiError(409, "registration_failed", "Could not create an account."), "Could not create"],
    [apiError(401, "invalid_credentials", "Email or password is incorrect."), "is incorrect"],
    [apiError(429, "rate_limited", "Too many requests. Please wait."), "Too many requests"],
    [apiError(403, "origin_rejected", "Origin is not allowed."), "not allowed"],
    [new Response("Bad gateway", { status: 502 }), "Could not reach the server"],
  ])("shows the form error for response %#", async (response, text) => {
    respond(response);
    render(<AuthForm mode="login" />);
    submit("Sign in");
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("shows a message when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<AuthForm mode="login" />);
    submit("Sign in");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
  });

  it("can be submitted again after a failure", async () => {
    const fetchMock = respond(apiError(401, "invalid_credentials", "Email or password is incorrect."));
    render(<AuthForm mode="login" />);
    submit("Sign in");
    await screen.findByRole("alert");
    fetchMock.mockResolvedValueOnce(json(200, {}));
    submit("Sign in");
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("sends one request for two rapid submits", async () => {
    const fetchMock = respond(json(201, {}));
    const { container } = render(<AuthForm mode="register" />);
    const form = container.querySelector("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(screen.getByRole("button", { name: "Creating account…" })).toBeDisabled();
    await waitFor(() => expect(replace).toHaveBeenCalled());
    fireEvent.submit(form); // after success, before the next page has loaded
    expect(screen.getByRole("button")).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
