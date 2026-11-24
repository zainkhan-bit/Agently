// Real-browser check of the signed-in layout: landing, navigation, screen sizes, accessibility.
// Setup and how to run: see auth-browser-check.js. Run from the repository root, because axe-core
// is read from frontend/node_modules. Each run registers one throwaway account and
// deletes it at the end.
//
//   node "<playwright-skill dir>/run.js" docs/manual-checks/dashboard-browser-check.js

const path = require("path");
const { chromium } = require("playwright");
const deleteAccounts = require(path.resolve("docs/manual-checks/delete-accounts.js"));

const BASE = process.env.BASE_URL || "http://localhost:3000";
const AXE = path.resolve("frontend/node_modules/axe-core/axe.min.js");
const run = Date.now();
const email = `browser-check-dashboard-${run}@example.com`;
const password = `check ${Math.random()} ${Math.random()}`;
const longName = `Long${"w".repeat(90)}`;
const SIZES = { narrow: [320, 640], mobile: [375, 700], tablet: [768, 1024], laptop: [1280, 800] };

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

async function signIn(page) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function main(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  context.setDefaultTimeout(30000);
  const page = await context.newPage();
  const menu = page.getByRole("button", { name: "Menu" });
  const switcher = page.getByRole("button", { name: /^Workspace/ });
  const nav = page.getByRole("navigation", { name: "Main" });
  const heading = (name) => page.getByRole("heading", { level: 1, name });

  await page.goto(BASE, { waitUntil: "networkidle" });
  check("signed-out home offers sign in", await page.getByRole("link", { name: "Sign in" }).isVisible());
  for (const target of ["/dashboard", "/account", "/workspaces", `/workspaces/${crypto.randomUUID()}`]) {
    await page.goto(`${BASE}${target}`);
    await page.waitForURL(`${BASE}/login`);
  }
  check("every signed-in page sends a signed-out visitor to login", true);

  await page.goto(`${BASE}/register`, { waitUntil: "networkidle" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  registered.push(email);
  await page.getByRole("button", { name: "Create account" }).click();
  await heading("Personal workspace").waitFor();
  const first = page.url();
  check("registering opens the workspace dashboard", /\/workspaces\/[0-9a-f-]{36}$/.test(first));
  check("the page title names the page", (await page.title()).startsWith("Dashboard"));

  await switcher.click();
  await page.getByRole("link", { name: "New workspace" }).click();
  await page.getByLabel("New workspace name").fill(longName);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await heading(longName).waitFor();
  const second = page.url();
  await switcher.getByText(longName).waitFor();
  check("a new workspace appears in the switcher", true);

  await switcher.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await heading("Personal workspace").waitFor();
  check("the keyboard switches workspace", page.url() === first);
  check(
    "switching moves focus to the new workspace's heading and titles the page",
    (await heading("Personal workspace").evaluate((el) => el === document.activeElement)) &&
      (await page.title()).startsWith("Dashboard: Personal workspace"),
  );
  await page.goto(second);
  await heading(longName).waitFor();

  await page.goto(BASE);
  await page.getByRole("link", { name: "Go to dashboard" }).click();
  await page.waitForURL(second);
  check("home offers the last-used dashboard when signed in", true);

  const stored = await page.evaluate(() => ({ ...localStorage }));
  const entries = Object.entries(stored).filter(([key]) => key.startsWith("agently"));
  const uuid = "[0-9a-f-]{36}";
  check(
    "storage holds only a workspace id under a user id",
    entries.length === 1 &&
      new RegExp(`^agently:last-workspace:${uuid}$`).test(entries[0][0]) &&
      second.endsWith(entries[0][1]) &&
      new RegExp(`^${uuid}$`).test(entries[0][1]),
  );

  for (const [size, [width, height]] of Object.entries(SIZES)) {
    await page.setViewportSize({ width, height });
    await page.goto(second);
    await heading(longName).waitFor();
    check(`${size}: menu button ${size === "laptop" ? "hidden" : "shown"}`, (await menu.isVisible()) === (size !== "laptop"));
    check(`${size}: sidebar ${size === "laptop" ? "shown" : "hidden"}`, (await nav.isVisible()) === (size === "laptop"));
    await accessible(page, `${size} dashboard`);
    if (size !== "laptop") await menu.click();
    await switcher.click();
    await accessible(page, `${size} with menu and switcher open`);
    await nav.getByRole("link", { name: "Settings" }).click();
    await heading("Workspace settings").waitFor();
    check(`${size}: navigation moves focus to the new heading`, await heading("Workspace settings").evaluate((el) => el === document.activeElement));
    if (size !== "laptop") check(`${size}: navigation closes the menu`, !(await nav.isVisible()));
    await accessible(page, `${size} settings`);
    for (const [target, title] of [[`${new URL(second).pathname}/agents`, "My Agents"], ["/workspaces", "Workspaces"], ["/account", "Account"], [`/workspaces/${crypto.randomUUID()}`, "Workspace not found"]]) {
      await page.goto(`${BASE}${target}`);
      await heading(title).waitFor();
      await accessible(page, `${size} ${title}`);
    }
  }
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(second);
  await heading(longName).waitFor();
  await accessible(page, "dark dashboard");
  await page.emulateMedia({ colorScheme: "light" });

  // Keyboard only, at phone width.
  await page.setViewportSize({ width: 375, height: 700 });
  await page.goto(second);
  await heading(longName).waitFor();
  await page.keyboard.press("Tab");
  check("the first Tab stop is the skip link", (await page.evaluate(() => document.activeElement.textContent)) === "Skip to content");
  await page.keyboard.press("Enter");
  check("the skip link moves focus to the page", (await page.evaluate(() => document.activeElement.id)) === "content");
  await menu.focus();
  await page.keyboard.press("Enter");
  check("Enter opens the menu", await nav.isVisible());
  await page.keyboard.press("Tab");
  check("Tab goes from the menu button into the menu", await switcher.evaluate((el) => el === document.activeElement));
  check("keyboard focus is visible", (await switcher.evaluate((el) => getComputedStyle(el).outlineStyle)) === "solid");
  await page.keyboard.press("Escape");
  check("Escape closes the menu and returns focus", !(await nav.isVisible()) && (await menu.evaluate((el) => el === document.activeElement)));

  // Server failure: a retry, not a login redirect.
  await page.route("**/api/workspaces", (route) => route.abort());
  await page.goto(second);
  await page.getByRole("button", { name: "Retry" }).waitFor();
  check("a server failure offers a retry", page.url() === second);
  await accessible(page, "error");
  await page.unroute("**/api/workspaces");
  await page.getByRole("button", { name: "Retry" }).click();
  await heading(longName).waitFor();
  check("retry recovers", true);

  await menu.click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(`${BASE}/login`);
  await page.goBack();
  await page.waitForURL(`${BASE}/login`);
  check("Back after sign out does not show the dashboard", !(await page.content()).includes(longName));
  await signIn(page);
  await page.waitForURL(second);
  check("signing in again opens the last-used workspace", true);

  await page.goto(`${second}/settings`);
  await page.getByLabel("Workspace name").fill(longName);
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await page.waitForURL(first);
  check("deleting opens the next workspace", true);
  await page.goto(`${first}/settings`);
  await page.getByLabel("Workspace name").fill("Personal workspace");
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await page.getByText("Create your first workspace").waitFor();
  check("deleting the last one opens the create form", page.url() === `${BASE}/workspaces`);
  await menu.click();
  check("without a workspace only Account is in the menu", (await nav.getByRole("link").allTextContents()).join() === "Account");
  await page.reload();

  // Sign-in must work where storage is blocked.
  const blocked = await browser.newContext();
  blocked.setDefaultTimeout(30000);
  await blocked.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new DOMException("denied", "SecurityError");
      },
    });
  });
  const blockedPage = await blocked.newPage();
  await signIn(blockedPage);
  await blockedPage.getByText("Create your first workspace").waitFor();
  await blockedPage.getByLabel("New workspace name").fill("No storage");
  await blockedPage.getByRole("button", { name: "Create workspace" }).click();
  await blockedPage.getByRole("heading", { level: 1, name: "No storage" }).waitFor();
  check("sign-in and the dashboard work with storage blocked", true);
}

(async () => {
  const browser = await chromium.launch();
  try {
    await main(browser);
  } catch (error) {
    check(`journey completed (${error.message.split("\n")[0]})`, false);
  } finally {
    await browser.close();
    check("the run's accounts are deleted", deleteAccounts(registered));
  }
  console.log(failures ? `${failures} check(s) FAILED` : "All checks passed");
  process.exitCode = failures ? 1 : 0;
})();
