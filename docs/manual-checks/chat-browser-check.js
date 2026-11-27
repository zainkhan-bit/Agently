// Real-browser check of chat: streaming, stopping, retrying, plain text, privacy between members,
// paused agents, owner warnings, screen sizes, accessibility. Setup: see agents-browser-check.js.
// The backend must run with MODEL_PROVIDER=mock and MOCK_PROVIDER_SCENARIO=slow, so that an answer
// takes long enough to watch and to stop. Never against a real provider. Registers two throwaway
// accounts and deletes them at the end.
//
//   node "<playwright-skill dir>/run.js" docs/manual-checks/chat-browser-check.js

const path = require("path");
const { spawnSync } = require("child_process");
const { chromium } = require("playwright");
const deleteAccounts = require(path.resolve("docs/manual-checks/delete-accounts.js"));

const BASE = process.env.BASE_URL || "http://localhost:3000";
const AXE = path.resolve("frontend/node_modules/axe-core/axe.min.js");
const run = Date.now();
const password = `check ${Math.random()} ${Math.random()}`;
const SIZES = { narrow: [320, 640], mobile: [375, 700], tablet: [768, 1024], laptop: [1280, 800] };
const ID = "[0-9a-f-]{36}";

const registered = [];
let failures = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
}

async function accessible(page, name) {
  await page.addScriptTag({ path: AXE });
  const violations = await page.evaluate(async () =>
    (await window.axe.run()).violations.map(
      ({ id, nodes }) => `${id}: ${nodes.map((node) => node.target).join(", ")}`,
    ),
  );
  violations.forEach((text) => console.log(`      ${text}`));
  check(`${name}: no accessibility violations`, violations.length === 0);
  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  check(`${name}: no horizontal scroll`, !overflows);
}

async function signUp(browser, name) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  context.setDefaultTimeout(15000);
  const page = await context.newPage();
  const email = `browser-check-chat-${name}-${run}@example.com`;
  await page.goto(`${BASE}/register`, { waitUntil: "networkidle" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  registered.push(email);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL(new RegExp(`/workspaces/${ID}$`));
  return { context, page, email, workspace: page.url() };
}

/** Make B a member of A's workspace, directly in the local database. */
function addMember(email, workspaceId) {
  const code = [
    "import sys, uuid",
    "from sqlalchemy import select",
    "from app.core.database import get_session_factory",
    "from app.models import Membership, User",
    "with get_session_factory()() as s:",
    "    user = s.scalar(select(User).where(User.email == sys.argv[1]))",
    "    s.add(Membership(user_id=user.id, workspace_id=uuid.UUID(sys.argv[2]), role='member'))",
    "    s.commit()",
  ].join("\n");
  const result = spawnSync(path.resolve("backend/.venv/Scripts/python.exe"), ["-c", code, email, workspaceId], {
    cwd: path.resolve("backend"),
    encoding: "utf8",
  });
  if (result.status !== 0) throw new Error(`could not add the member: ${result.stderr}`);
}

async function main(browser) {
  const a = await signUp(browser, "a");
  const { page, context, workspace } = a;
  const api = workspace.replace("/workspaces/", "/api/workspaces/");
  const headers = { Origin: BASE };
  const heading = (name) => page.getByRole("heading", { level: 1, name, exact: true });
  const button = (name) => page.getByRole("button", { name, exact: true });
  const status = page.locator("main [role=status]").last();
  const dialogs = [];
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.message());
    await dialog.accept();
  });

  const agent = await (await context.request.post(`${api}/agents`, {
    headers,
    data: { name: "Helper", instructions: "Be kind." },
  })).json();
  const agentUrl = `${workspace}/agents/${agent.id}`;

  // From the agent to a new conversation.
  await page.goto(agentUrl);
  await heading("Helper").waitFor();
  check("owners are told that deleting the agent deletes everyone's conversations", await page.getByText("everyone's conversations with it").isVisible());
  await page.getByRole("link", { name: "Chat with this agent" }).click();
  await heading("Conversations with Helper").waitFor();
  await page.getByText("No conversations yet.").waitFor();
  await accessible(page, "empty list");
  await button("New conversation").click();
  await page.waitForURL(new RegExp(`/conversations/${ID}$`));
  const chatUrl = page.url();
  await heading("Chat with Helper").waitFor();
  await page.getByText("No messages yet.").waitFor();
  await accessible(page, "empty chat");

  // Streaming, in order, as plain text.
  const evil = `<img src=x onerror="window.hit=1"><script>window.hit=1</script> **not bold**`;
  const box = page.getByLabel("Message");
  await box.fill(evil);
  await box.press("Enter");
  await status.filter({ hasText: "answering" }).waitFor();
  const firstPiece = await page.locator("main ol li").last().innerText();
  await status.filter({ hasText: "Answer complete." }).waitFor({ timeout: 30000 });
  const answer = await page.locator("main ol li").last().innerText();
  check("the answer arrived in pieces", firstPiece.length < answer.length);
  check("and ends with the message, as text", answer.includes("Sample answer, made without AI.") && answer.includes(evil));
  const ran = await page.evaluate(() => "hit" in window || document.querySelector("main ol script, main ol img, main ol strong") !== null);
  check("nothing typed or answered runs as HTML", !ran);
  check("the composer is empty again", (await box.inputValue()) === "");
  await accessible(page, "chat with an answer");

  // Refresh keeps it.
  await page.reload();
  await heading("Chat with Helper").waitFor();
  check("refreshing restores the conversation", (await page.locator("main ol li").count()) === 2 && (await page.getByText(evil).count()) === 2);

  // Stop.
  await box.fill("Please stop");
  await button("Send").click();
  await status.filter({ hasText: "answering" }).waitFor();
  await button("Stop answering").click();
  await status.filter({ hasText: "Stopped" }).waitFor();
  check("stopping says nothing was saved", (await status.innerText()).includes("Stopped. No answer was saved."));
  await page.waitForTimeout(3000); // the cancelled answer would have finished by now
  const afterStop = await (await context.request.get(`${chatUrl.replace("/workspaces/", "/api/workspaces/")}/messages`)).json();
  check("a stopped answer is not stored", afterStop.items.length === 3 && afterStop.items[2].role === "user");
  await accessible(page, "stopped");

  // Retry after reload, the same request.
  await page.reload();
  await button("Retry the last message").click();
  await status.filter({ hasText: "Answer complete." }).waitFor({ timeout: 30000 });
  const afterRetry = await (await context.request.get(`${chatUrl.replace("/workspaces/", "/api/workspaces/")}/messages`)).json();
  check("retrying answers the same message without storing it again", afterRetry.items.length === 4 && afterRetry.items.filter((m) => m.content === "Please stop").length === 1);

  // Double submit.
  await box.fill("Once");
  await box.press("Enter");
  await box.press("Enter");
  await button("Send").click({ force: true });
  await status.filter({ hasText: "Answer complete." }).waitFor({ timeout: 30000 });
  const afterOnce = await (await context.request.get(`${chatUrl.replace("/workspaces/", "/api/workspaces/")}/messages`)).json();
  check("sending twice quickly stores one message", afterOnce.items.filter((m) => m.content === "Once").length === 1);

  // A stop, then a new message straight away, without reloading.
  await box.fill("Stop me too");
  await button("Send").click();
  await status.filter({ hasText: "answering" }).waitFor();
  await button("Stop answering").click();
  await status.filter({ hasText: "Stopped" }).waitFor();
  check("after a stop, retry is offered at once", await button("Retry the last message").isVisible());
  await box.fill("A new one");
  await box.press("Enter");
  await status.filter({ hasText: "Answer complete." }).waitFor({ timeout: 30000 });
  const afterNew = await (await context.request.get(`${chatUrl.replace("/workspaces/", "/api/workspaces/")}/messages`)).json();
  const last = afterNew.items.slice(-3).map((m) => [m.role, m.content.includes("A new one") || m.content === "Stop me too"]);
  check("a new message can be sent right after a stop", JSON.stringify(last) === JSON.stringify([["user", true], ["user", true], ["assistant", true]]));

  // Privacy between members.
  const b = await signUp(browser, "b");
  addMember(b.email, workspace.split("/").pop());
  await b.page.goto(chatUrl);
  await b.page.getByRole("heading", { name: "Conversation not found" }).waitFor();
  check("another member cannot open it", !(await b.page.locator("main").innerText()).includes("Please stop"));
  await b.page.goto(`${agentUrl}/conversations`);
  await b.page.getByText("No conversations yet.").waitFor();
  check("nor see it listed", true);
  check("members are not offered to delete the agent", (await b.page.goto(agentUrl), await b.page.getByRole("heading", { name: "Delete agent" }).count()) === 0);

  // Paused.
  await page.goto(agentUrl);
  await button("Pause").click();
  await page.getByText("Status: Paused.").waitFor();
  await page.goto(chatUrl);
  await page.getByText("This agent is paused. It cannot answer until it is resumed.").waitFor();
  check("a paused agent cannot be sent to", await page.getByLabel("Message").isDisabled());
  await accessible(page, "paused");
  await page.goto(`${agentUrl}/conversations`);
  check("nor can a conversation be started", (await button("New conversation").count()) === 0);
  await page.goto(agentUrl);
  await button("Resume").click();
  await page.getByText("Status: Active.").waitFor();

  // Workspace warning.
  await page.goto(`${workspace}/settings`);
  await page.getByRole("heading", { name: "Delete workspace" }).waitFor();
  check("owners are told that deleting the workspace deletes everyone's conversations", await page.getByText("private conversations with them, which you cannot see").isVisible());

  // Sizes and colours.
  for (const [size, [width, height]] of Object.entries(SIZES)) {
    await page.setViewportSize({ width, height });
    await page.goto(chatUrl);
    await heading("Chat with Helper").waitFor();
    await accessible(page, `${size} chat`);
    await page.goto(`${agentUrl}/conversations`);
    await heading("Conversations with Helper").waitFor();
    await accessible(page, `${size} list`);
  }
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(chatUrl);
  await heading("Chat with Helper").waitFor();
  await accessible(page, "dark chat");
  if (process.env.SCREENSHOTS) {
    await page.setViewportSize({ width: 375, height: 700 });
    await page.screenshot({ path: path.join(process.env.SCREENSHOTS, "chat-mobile.png"), fullPage: true });
  }

  // Deleting.
  await page.goto(chatUrl);
  await button("Delete permanently").click();
  await page.waitForURL(`${agentUrl}/conversations`);
  await page.getByText("No conversations yet.").waitFor();
  check("deleting asks first and removes it", dialogs.some((text) => text.includes("Delete this conversation")) && (await page.getByText("No conversations yet.").count()) === 1);
}

(async () => {
  const browser = await chromium.launch();
  try {
    await main(browser);
  } catch (error) {
    check(`journey completed (${error.message.split("\n").slice(0, 3).join(" ")})`, false);
  } finally {
    await browser.close();
    check("the run's accounts are deleted", deleteAccounts(registered));
  }
  console.log(failures ? `${failures} check(s) FAILED` : "All checks passed");
  process.exitCode = failures ? 1 : 0;
})();
