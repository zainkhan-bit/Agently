// Real-browser check of version history and rollback. Setup and how to run: see
// agents-browser-check.js. Registers two throwaway accounts and deletes them at the end.
//
//   node "<playwright-skill dir>/run.js" docs/manual-checks/versions-browser-check.js

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
  const email = `browser-check-versions-${name}-${run}@example.com`;
  await page.goto(`${BASE}/register`, { waitUntil: "networkidle" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  registered.push(email);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL(new RegExp(`/workspaces/${ID}$`));
  return { context, page, email, workspace: page.url() };
}

async function main(browser) {
  const { context, page, email, workspace } = await signUp(browser, "a");
  const api = workspace.replace("/workspaces/", "/api/workspaces/");
  const headers = { Origin: BASE };
  const heading = (name) => page.getByRole("heading", { level: 1, name, exact: true });
  const focused = (locator) => locator.evaluate((el) => el === document.activeElement);
  const button = (name) => page.getByRole("button", { name, exact: true });
  const link = (name) => page.getByRole("link", { name, exact: true });
  const entries = page.locator("main ol > li");
  const dialogs = [];
  let accept = true;
  page.on("dialog", async (dialog) => {
    dialogs.push(`${dialog.type()}: ${dialog.message()}`);
    await (accept ? dialog.accept() : dialog.dismiss());
  });
  const asked = () => dialogs.splice(0).join();

  const create = async (data) =>
    (await context.request.post(`${api}/agents`, { headers, data })).json();
  const edit = (id, data) => context.request.patch(`${api}/agents/${id}`, { headers, data });
  const agentNow = async (id) => (await context.request.get(`${api}/agents/${id}`)).json();

  // History.
  const evil = `<img src=x onerror="window.hit=1;alert(1)"><script>window.hit=1</script>`;
  const agent = await create({ name: "Helper", instructions: "First text" });
  await edit(agent.id, { version: 1, instructions: evil });
  await edit(agent.id, { version: 2, name: "Renamed", purpose: "Support" });
  const url = `${workspace}/agents/${agent.id}`;
  await page.goto(url);
  await page.getByText("Version 3.").waitFor();
  await link("Version history").click();
  await heading("Version history of Renamed").waitFor();
  check("the history takes focus", await focused(heading("Version history of Renamed")));
  check("newest first, with the current one marked", (await entries.first().innerText()).includes("Version 3 (current)"));
  check("changed fields are named", (await entries.first().innerText()).includes("Changed: name, purpose"));
  check("the first one was created", (await entries.last().innerText()).includes("Created"));
  check("the saver is named", (await entries.last().innerText()).includes(`Saved by ${email}`));
  await accessible(page, "history");

  // One version.
  await link("Version 2").click();
  await heading("Version 2 of Renamed").waitFor();
  check("a version takes focus", await focused(heading("Version 2 of Renamed")));
  await page.getByText(evil, { exact: true }).waitFor();
  const ran = await page.evaluate(
    () => "hit" in window || document.querySelector("main script, main img") !== null,
  );
  check("saved markup is plain text", !ran && asked() === "");
  check("a version has nothing to edit", (await page.getByRole("textbox").count()) === 0);
  await accessible(page, "version");
  await link("Version history").click();
  await heading("Version history of Renamed").waitFor();
  await link("Version 3").click();
  await page.getByText("This is the current version.").waitFor();
  check("the current version cannot be rolled back to", (await page.getByRole("button", { name: /Roll back/ }).count()) === 0);

  // Rollback.
  await page.goto(`${url}/versions`);
  await link("Version 1").click();
  await heading("Version 1 of Renamed").waitFor();
  const firstUrl = page.url();
  accept = false;
  await button("Roll back to version 1").click();
  check("rolling back asks, and declining saves nothing", asked().startsWith("confirm: Roll back to version 1?") && (await agentNow(agent.id)).version === 3);
  accept = true;
  await page.route("**/rollback", (route) => route.abort());
  await button("Roll back to version 1").click();
  await page.getByText("may have been made").waitFor();
  check("an unclear failure is said to be unclear", (await agentNow(agent.id)).version === 3);
  await accessible(page, "version with an error");
  await page.unroute("**/rollback");
  asked();
  await button("Roll back to version 1").focus();
  await page.keyboard.press("Enter");
  await page.waitForURL(url);
  await heading("Helper").waitFor();
  await page.getByText("Version 4.").waitFor();
  check("rolling back opens the agent with its old configuration", await page.getByText("First text", { exact: true }).isVisible());
  check("and focuses its heading", await focused(heading("Helper")));
  asked();
  await page.reload();
  await page.getByText("Version 4.").waitFor();
  await link("Version history").click();
  await heading("Version history of Helper").waitFor();
  check("history names the source", (await entries.first().innerText()).includes("Restored from version 1. Changed: name, purpose, instructions"));
  check("and keeps every version", (await entries.count()) === 4);

  // Nothing to change.
  await page.goto(firstUrl);
  await button("Roll back to version 1").click();
  await page.getByText("Nothing changed").waitFor();
  check("an equal version saves nothing", (await agentNow(agent.id)).version === 4);
  await accessible(page, "nothing changed");

  // Changed elsewhere.
  await page.goto(firstUrl);
  await button("Roll back to version 1").waitFor();
  await edit(agent.id, { version: 4, name: "Elsewhere" });
  asked();
  await button("Roll back to version 1").click();
  await page.getByText("has changed since you opened it").waitFor();
  check("a stale page saves nothing", (await agentNow(agent.id)).version === 5);
  await accessible(page, "stale");
  await button("Load the latest").click();
  await page.getByText("The current version is 5.").waitFor();
  await button("Roll back to version 1").click();
  await page.waitForURL(url);
  await page.getByText("Version 6.").waitFor();
  check("after loading the latest it works", true);
  asked();

  // Archived.
  await button("Archive").click();
  await page.getByText("Status: Archived.").waitFor();
  await link("Version history").click();
  await heading("Version history of Helper").waitFor();
  await link("Version 2").click();
  await page.getByText("An archived agent cannot be rolled back.").waitFor();
  check("an archived agent shows history without rollback", (await page.getByRole("button", { name: /Roll back/ }).count()) === 0);

  // Pages.
  const long = await create({ name: `Long${"w".repeat(90)}`, instructions: "0" });
  for (let version = 1; version < 23; version += 1) {
    await edit(long.id, { version, instructions: String(version) });
  }
  const longUrl = `${workspace}/agents/${long.id}/versions`;
  await page.goto(longUrl);
  await entries.first().waitFor();
  check("20 versions are shown first", (await entries.count()) === 20);
  check("the last one on the page is compared too", (await entries.last().innerText()).includes("Changed: instructions"));
  await button("Show older versions").click();
  await page.waitForFunction(() => document.querySelectorAll("main ol > li").length === 23);
  check("and the rest on request", (await page.getByRole("button", { name: "Show older versions" }).count()) === 0);
  check("focus is not lost with the button", await page.evaluate(() => document.activeElement !== document.body));

  // Isolation.
  const other = await create({ name: "Other", instructions: "Other secret" });
  const versions = await (await context.request.get(`${api}/agents/${other.id}/versions`)).json();
  const foreign = versions.items[0].id;
  await page.goto(`${longUrl}/${foreign}`);
  await page.getByRole("heading", { name: "Version not found" }).waitFor();
  check("another agent's version is not found", !(await page.locator("main").innerText()).includes("Other"));
  await accessible(page, "version not found");
  await page.goto(`${longUrl}/not-an-id`);
  await page.getByRole("heading", { name: "Version not found" }).waitFor();
  const crossed = await context.request.post(`${api}/agents/${long.id}/versions/${foreign}/rollback`, {
    headers,
    data: { version: 23 },
  });
  check("nor can it be rolled back to", crossed.status() === 404 && (await agentNow(long.id)).version === 23);
  const b = await signUp(browser, "b");
  for (const target of [longUrl, `${longUrl}/${foreign}`, firstUrl]) {
    await b.page.goto(target);
    await b.page.getByText("Workspace not found").waitFor();
  }
  await b.page.goto(`${b.workspace}/agents/${long.id}/versions`);
  await b.page.getByText("Agent not found").waitFor();
  check("another account sees nothing", !(await b.page.locator("main").innerText()).includes("Long"));

  // Sizes and colours.
  const first = (await (await context.request.get(`${api}/agents/${long.id}/versions?before=2`)).json()).items[0].id;
  const pages = [
    ["history", longUrl, `Version history of ${long.name}`],
    ["version", `${longUrl}/${first}`, `Version 1 of ${long.name}`],
  ];
  for (const [size, [width, height]] of Object.entries(SIZES)) {
    await page.setViewportSize({ width, height });
    for (const [name, target, title] of pages) {
      await page.goto(target);
      await heading(title).waitFor();
      await accessible(page, `${size} ${name}`);
    }
  }
  await page.emulateMedia({ colorScheme: "dark" });
  for (const [name, target, title] of pages) {
    await page.goto(target);
    await heading(title).waitFor();
    await accessible(page, `dark ${name}`);
  }
  if (process.env.SCREENSHOTS) {
    await page.emulateMedia({ colorScheme: "light" });
    for (const [name, target, title] of pages) {
      await page.goto(target);
      await heading(title).waitFor();
      await page.screenshot({ path: path.join(process.env.SCREENSHOTS, `versions-${name}.png`) });
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
