// Real-browser check of workspaces and tenant isolation through the Next.js /api proxy.
// Setup and how to run: see auth-browser-check.js. Each run registers two throwaway accounts.
//
//   node "<playwright-skill dir>/run.js" docs/manual-checks/workspace-browser-check.js

const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://localhost:3000";
const run = Date.now();
const password = `check ${Math.random()} ${Math.random()}`;

let failures = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
}

async function signUp(browser, name) {
  const context = await browser.newContext();
  context.setDefaultTimeout(30000);
  const page = await context.newPage();
  const email = `browser-check-${name}-${run}@example.com`;
  await page.goto(`${BASE}/register`, { waitUntil: "networkidle" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByText(`Signed in as ${email}`).waitFor();
  return { context, page, email };
}

async function noOverflow(page) {
  await page.setViewportSize({ width: 375, height: 700 });
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
}

async function main(browser) {
  const a = await signUp(browser, "a");
  await a.page.getByRole("link", { name: "Workspaces" }).click();
  await a.page.getByRole("link", { name: "Personal workspace" }).waitFor();
  check("a new account has a personal workspace", true);

  const name = `Private ${run} ${"x".repeat(70)}`;
  await a.page.getByLabel("New workspace name").fill(name);
  await a.page.getByRole("button", { name: "Create workspace" }).click();
  await a.page.getByRole("heading", { name }).waitFor();
  const url = a.page.url();
  check("creating opens the new workspace", /\/workspaces\/[0-9a-f-]{36}$/.test(url));
  check("its member list shows the owner", await a.page.getByText(`${a.email} (owner)`).isVisible());
  check("no horizontal scroll at phone width", await noOverflow(a.page));

  const b = await signUp(browser, "b");
  await b.page.goto(url);
  await b.page.getByText("Workspace not found").waitFor();
  const html = await b.page.content();
  check("another account sees 'not found'", true);
  check("and none of its data", !html.includes(name) && !html.includes(a.email));

  const api = url.replace("/workspaces/", "/api/workspaces/");
  const headers = { Origin: BASE };
  const attempts = [
    await b.context.request.get(api),
    await b.context.request.get(`${api}/members`),
    await b.context.request.patch(api, { headers, data: { name: "Taken" } }),
    await b.context.request.delete(api, { headers }),
    await b.context.request.post(`${api}/leave`, { headers }),
  ];
  check(
    "another account gets 404 from every endpoint",
    attempts.every((response) => response.status() === 404),
  );
  await b.page.goto(`${BASE}/workspaces`);
  await b.page.getByRole("link", { name: "Personal workspace" }).waitFor();
  check("and does not see it listed", !(await b.page.content()).includes(name));
  check("no horizontal scroll on the list", await noOverflow(b.page));

  await a.page.reload();
  await a.page.getByRole("heading", { name }).waitFor();
  check("the workspace is unchanged", true);
  const button = a.page.getByRole("button", { name: "Delete permanently" });
  check("delete is off until the name is typed", await button.isDisabled());
  await a.page.getByLabel("Workspace name").fill(name);
  await button.click();
  await a.page.waitForURL(`${BASE}/workspaces`);
  await a.page.getByRole("link", { name: "Personal workspace" }).waitFor();
  check("deleting returns to the list without it", !(await a.page.content()).includes(name));
  await a.page.goto(url);
  await a.page.getByText("Workspace not found").waitFor();
  check("the deleted workspace is gone", true);

  await a.context.clearCookies();
  await a.page.goto(`${BASE}/workspaces`);
  await a.page.waitForURL(`${BASE}/login`);
  check("signed-out visitors go to login", true);
}

(async () => {
  const browser = await chromium.launch();
  try {
    await main(browser);
  } catch (error) {
    check(`journey completed (${error.message.split("\n")[0]})`, false);
  } finally {
    await browser.close();
  }
  console.log(failures ? `${failures} check(s) FAILED` : "All checks passed");
  process.exitCode = failures ? 1 : 0;
})();
