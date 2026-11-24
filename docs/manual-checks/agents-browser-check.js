// Real-browser check of My Agents: the whole journey, plain-text rendering, isolation, unsaved
// text, screen sizes, accessibility. Setup and how to run: see auth-browser-check.js. Run from the
// repository root, because axe-core is read from frontend/node_modules. Each run registers two
// throwaway accounts and deletes them at the end.
//
//   node "<playwright-skill dir>/run.js" docs/manual-checks/agents-browser-check.js

const path = require("path");
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
  const email = `browser-check-agents-${name}-${run}@example.com`;
  await page.goto(`${BASE}/register`, { waitUntil: "networkidle" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  registered.push(email);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL(new RegExp(`/workspaces/${ID}$`));
  return { context, page, workspace: page.url() };
}

async function main(browser) {
  const { context, page, workspace } = await signUp(browser, "a");
  const api = workspace.replace("/workspaces/", "/api/workspaces/");
  const headers = { Origin: BASE };
  const heading = (name) => page.getByRole("heading", { level: 1, name, exact: true });
  const focused = (locator) => locator.evaluate((el) => el === document.activeElement);
  const button = (name) => page.getByRole("button", { name, exact: true });
  const field = (name) => page.getByLabel(new RegExp(`^${name} \\(`));
  const nav = page.getByRole("navigation", { name: "Main" });

  // Every browser dialog is counted; an alert() would mean that saved text was executed.
  const dialogs = [];
  let accept = true;
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.type());
    await (accept ? dialog.accept() : dialog.dismiss());
  });
  const asked = () => dialogs.splice(0).join();

  // Create, view, list.
  await page.getByText("0 current agents").waitFor();
  check("the dashboard shows the real number of agents", true);
  await nav.getByRole("link", { name: "My Agents" }).click();
  await page.getByText("No current agents").waitFor();
  check("empty list says what to do", true);
  check("navigation moves focus to the heading", await focused(heading("My Agents")));
  await accessible(page, "empty list");
  await page.getByRole("link", { name: "New agent" }).click();
  await heading("New agent").waitFor();
  await button("Create agent").click();
  await page.getByText("Name is required.").waitFor();
  check("an empty form focuses the first problem", await focused(field("Name")));
  await accessible(page, "form with errors");

  await field("Name").fill("Too long");
  await field("Instructions").fill("x".repeat(10001));
  check("the counter counts", await page.getByText("10,001 / 10,000").isVisible());
  await accessible(page, "form over the limit");
  let posts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/agents")) posts += 1;
  });
  await button("Create agent").click();
  await page.getByText("at most 10,000 characters").waitFor();
  check("over the limit nothing is sent", posts === 0);

  const evil = (name) =>
    `<script>window.hit=1;alert(1)</script><img src=x onerror="window.hit=1;alert(1)">${name}`;
  const fields = ["Name", "Purpose", "Description", "Instructions"];
  for (const name of fields) await field(name).fill(evil(name));
  await button("Create agent").click();
  await page.waitForURL(new RegExp(`/agents/${ID}$`));
  await heading(evil("Name")).waitFor();
  const evilUrl = page.url();
  check("saving asks nothing and opens the agent", asked() === "");
  check("saving moves focus to the agent's heading", await focused(heading(evil("Name"))));

  async function inert(where) {
    const ran = await page.evaluate(
      () => "hit" in window || document.querySelector("main script, main img") !== null,
    );
    check(`${where}: saved markup is plain text`, !ran && asked() === "");
  }
  for (const name of fields) await page.getByText(evil(name), { exact: true }).first().waitFor();
  await inert("agent page");
  await page.reload();
  for (const name of fields) await page.getByText(evil(name), { exact: true }).first().waitFor();
  check("a reload shows the same configuration", true);
  await inert("agent page after reload");
  await page.getByRole("link", { name: "Edit" }).click();
  await heading(`Edit ${evil("Name")}`).waitFor();
  for (const name of fields) {
    check(`edit form keeps ${name} literally`, (await field(name).inputValue()) === evil(name));
  }
  await inert("edit form");
  await page.goto(`${workspace}/agents`);
  await page.getByText(evil("Name"), { exact: true }).waitFor();
  await page.getByText(evil("Purpose"), { exact: true }).waitFor();
  await inert("list");

  // Status changes, from the keyboard.
  await page.goto(evilUrl);
  await heading(evil("Name")).waitFor();
  await button("Pause").focus();
  await page.keyboard.press("Enter");
  await page.getByText("Status: Paused.").waitFor();
  check("pausing keeps focus on the button", await focused(button("Resume")));
  await page.reload();
  await page.getByText("Status: Paused.").waitFor();
  check("pausing survives a refresh", true);
  await page.route("**/resume", (route) => route.abort());
  await button("Resume").click();
  await page.getByText("may have been made").waitFor();
  check("a failed change changes nothing on screen", await page.getByText("Status: Paused.").isVisible());
  await accessible(page, "agent with an error");
  await page.unroute("**/resume");
  await button("Resume").click();
  await page.getByText("Status: Active.").waitFor();
  await button("Archive").click();
  await page.getByText("Status: Archived.").waitFor();
  check("an archived agent cannot be edited", (await page.getByRole("link", { name: "Edit" }).count()) === 0);
  await page.goto(`${evilUrl}/edit`);
  await page.getByText("Restore it first").waitFor();
  await page.goto(`${workspace}/agents`);
  await page.getByText("No current agents").waitFor();
  await page.getByRole("link", { name: "Archived", exact: true }).click();
  await page.getByText(evil("Name"), { exact: true }).waitFor();
  check("the archived view takes focus and survives a refresh", await focused(heading("Archived agents")));
  await page.reload();
  await page.getByText(evil("Name"), { exact: true }).click();
  await button("Restore").click();
  await page.getByText("Status: Paused.").waitFor();
  check("restoring makes it paused", true);

  // Conflicts: one agent, changed elsewhere while the form is open.
  const create = async (name) =>
    (
      await context.request.post(`${api}/agents`, {
        headers,
        data: { name, instructions: "Original" },
      })
    ).json();
  const helper = await create("Helper");
  const helperUrl = `${workspace}/agents/${helper.id}`;
  const elsewhere = (version, instructions) =>
    context.request.patch(`${api}/agents/${helper.id}`, { headers, data: { version, instructions } });
  await page.goto(`${helperUrl}/edit`);
  await field("Instructions").fill("Mine");
  await elsewhere(1, "Theirs");
  await button("Save changes").click();
  await page.getByText("has changed since you opened it").waitFor();
  check("a conflict keeps the text", (await field("Instructions").inputValue()) === "Mine");
  await accessible(page, "conflict");
  accept = false;
  await button("Discard my text and load the latest").click();
  check("discarding asks first", asked() === "confirm" && (await field("Instructions").inputValue()) === "Mine");
  accept = true;
  await button("Discard my text and load the latest").click();
  await page.waitForFunction(() => document.querySelector("#agent-instructions")?.value === "Theirs");
  asked();
  await field("Instructions").fill("Mine again");
  await button("Save changes").click();
  await page.waitForURL(helperUrl); // the form shows the same text
  await page.locator("dd", { hasText: "Mine again" }).waitFor();
  check("and the next save works", asked() === "");

  // Unsaved text.
  await page.goto(`${workspace}/agents`);
  await page.getByRole("link", { name: "Helper" }).click();
  await page.getByRole("link", { name: "Edit" }).click();
  const formUrl = `${helperUrl}/edit`;
  const typed = async () => {
    await field("Instructions").click();
    await page.keyboard.type("z");
  };
  await page.waitForURL(formUrl);
  await page.getByRole("link", { name: "Cancel" }).click();
  await page.waitForURL(helperUrl);
  check("leaving an unchanged form asks nothing", asked() === "");
  await page.getByRole("link", { name: "Edit" }).click();
  await page.waitForURL(formUrl);
  await typed();
  const text = await field("Instructions").inputValue();
  const kept = async () =>
    page.url() === formUrl && (await field("Instructions").inputValue()) === text;
  accept = false;
  await page.getByRole("link", { name: "Cancel" }).click();
  check("a link asks, and staying keeps the text", asked() === "confirm" && (await kept()));
  await nav.getByRole("link", { name: "Dashboard" }).click();
  check("the sidebar asks, and staying keeps the text", asked() === "confirm" && (await kept()));
  await button("Sign out").click();
  check("sign out asks, and staying keeps the text", asked() === "confirm" && (await kept()));
  for (const time of ["", " again"]) {
    await page.evaluate(() => history.back());
    await page.waitForTimeout(500);
    check(`Back asks${time}, and staying keeps the text`, asked() === "confirm" && (await kept()));
  }
  await page.evaluate(() => history.go(-3));
  await page.waitForTimeout(500);
  check("jumping further back asks, and staying keeps the text", asked() === "confirm" && (await kept()));
  const reload = page.reload({ timeout: 2000 }).catch(() => {});
  await reload;
  check("reloading asks, and staying keeps the text", asked() === "beforeunload" && (await kept()));
  accept = true;
  await page.getByRole("link", { name: "Cancel" }).click();
  await page.waitForURL(helperUrl);
  check("agreeing to leave leaves, asking once", asked() === "confirm");
  check("without saving", !(await page.content()).includes(text));
  await page.getByRole("link", { name: "Edit" }).click();
  await page.waitForURL(formUrl);
  await typed();
  await page.evaluate(() => history.back());
  await page.waitForURL(helperUrl);
  await heading("Helper").waitFor();
  check("agreeing to Back leaves, asking once", asked() === "confirm");
  await page.getByRole("link", { name: "Edit" }).click();
  await page.waitForURL(formUrl);
  await typed();
  await button("Save changes").click();
  await page.waitForURL(helperUrl);
  await heading("Helper").waitFor();
  check("saving asks nothing", asked() === "");

  // The session ends while text is unsaved.
  await page.getByRole("link", { name: "Edit" }).click();
  await page.waitForURL(formUrl);
  await typed();
  const cookies = await context.cookies();
  await context.clearCookies();
  await button("Save changes").click();
  await page.getByText("You are signed out. Nothing was saved.").waitFor();
  check("saving while signed out keeps the text", page.url() === formUrl);
  await accessible(page, "signed out with unsaved text");
  await context.addCookies(cookies);
  await button("Save changes").click();
  await page.waitForURL(helperUrl);
  check("and works after signing in again", asked() === "");

  // Busy: the API's answer, shown as it is.
  await page.route("**/pause", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: "busy", message: "The workspace is busy. Nothing was changed. Please try again." } },
    }),
  );
  await button("Pause").click();
  await page.getByText("The workspace is busy. Nothing was changed. Please try again.").waitFor();
  check("busy is explained", !(await page.content()).includes("may have been made"));
  await page.unroute("**/pause");

  // Duplicate, then delete the copy.
  await button("Duplicate").click();
  await heading("Copy of Helper").waitFor();
  await page.getByText("Status: Paused.").waitFor();
  check("duplicating opens a paused copy, with focus on its heading", await focused(heading("Copy of Helper")));
  check("delete is off until the name is typed", await button("Delete permanently").isDisabled());
  await page.getByLabel("Agent name").fill("Copy of Helper");
  await button("Delete permanently").click();
  await page.waitForURL(`${workspace}/agents`);
  await page.getByRole("link", { name: "Helper" }).waitFor();
  // Not the raw HTML: Next.js can leave the previous page's unused title element in it.
  const listed = (await page.locator("main").innerText()).includes("Copy of Helper");
  check("deleting returns to the list without it", !listed && (await page.title()).startsWith("My Agents"));

  // Isolation.
  const b = await signUp(browser, "b");
  for (const url of [helperUrl, `${helperUrl}/edit`, `${workspace}/agents`, `${workspace}/agents/new`]) {
    await b.page.goto(url);
    await b.page.getByText("Workspace not found").waitFor();
    check(`another account sees nothing at ${url.replace(workspace, "")}`, !(await b.page.content()).includes("Helper"));
  }
  for (const suffix of ["", "/edit"]) {
    await b.page.goto(`${b.workspace}/agents/${helper.id}${suffix}`);
    await b.page.getByText("Agent not found").waitFor();
    check(`nor through its own workspace${suffix}`, !(await b.page.content()).includes("Helper"));
  }
  await b.page.goto(`${b.workspace}/agents/${crypto.randomUUID()}`);
  await b.page.getByText("Agent not found").waitFor();
  await accessible(b.page, "agent not found");
  await b.page.goto(`${b.workspace}/agents/not-an-id`);
  await b.page.getByText("Agent not found").waitFor();
  check("a malformed id looks the same", true);

  // Sizes and colours.
  const long = await create(`Long${"w".repeat(90)}`);
  const pages = [
    ["list", `${workspace}/agents`, "My Agents"],
    ["archived", `${workspace}/agents?view=archived`, "Archived agents"],
    ["new", `${workspace}/agents/new`, "New agent"],
    ["agent", `${workspace}/agents/${long.id}`, long.name],
    ["edit", `${workspace}/agents/${long.id}/edit`, `Edit ${long.name}`],
  ];
  for (const [size, [width, height]] of Object.entries(SIZES)) {
    await page.setViewportSize({ width, height });
    for (const [name, url, title] of pages) {
      await page.goto(url);
      await heading(title).waitFor();
      await accessible(page, `${size} ${name}`);
    }
  }
  await page.emulateMedia({ colorScheme: "dark" });
  for (const [name, url, title] of pages) {
    await page.goto(url);
    await heading(title).waitFor();
    await accessible(page, `dark ${name}`);
  }
  if (process.env.SCREENSHOTS) {
    await page.emulateMedia({ colorScheme: "light" });
    for (const [size, [width, height]] of [["mobile", SIZES.mobile], ["laptop", SIZES.laptop]]) {
      await page.setViewportSize({ width, height });
      for (const [name, url, title] of pages) {
        await page.goto(url);
        await heading(title).waitFor();
        await page.screenshot({ path: path.join(process.env.SCREENSHOTS, `${size}-${name}.png`), fullPage: true });
      }
    }
  }
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
