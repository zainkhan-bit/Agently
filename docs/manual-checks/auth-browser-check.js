// Real-browser check of the auth journey through the Next.js /api proxy.
//
// Needs the frontend and backend running. Run from the repository root with the Playwright
// skill's runner (it brings its own Playwright, so the frontend needs no extra dependency):
//
//   node "<playwright-skill dir>/run.js" docs/manual-checks/auth-browser-check.js
//
// BASE_URL defaults to http://localhost:3000 and must be in the backend's ALLOWED_ORIGINS.
// Each run registers one throwaway account, so the backend needs a development signup limit
// (SIGNUP_LIMIT_PER_IP=100 and LOGIN_LIMIT_PER_IP=200, as in backend/.env.example) to be
// re-run often.
// EXPECT_SECURE=1 expects a Secure cookie (any ENVIRONMENT except development).

const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://localhost:3000";
const EXPECT_SECURE = process.env.EXPECT_SECURE === "1";
const COOKIE = process.env.COOKIE_NAME || "agently_session";
const email = `browser-check-${Date.now()}@example.com`;
const password = `check ${Math.random()} ${Math.random()}`;

let failures = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
}

async function submit(page, path, button) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: button }).click();
  await page.getByText(`Signed in as ${email}`).waitFor();
}

async function main(browser) {
  const context = await browser.newContext();
  context.setDefaultTimeout(30000);
  const page = await context.newPage();
  const sessionCookie = async () => (await context.cookies()).find((c) => c.name === COOKIE);

  await submit(page, "/register", "Create account");
  check("register opens the signed-in view", page.url() === `${BASE}/account`);

  await page.reload();
  await page.getByText(`Signed in as ${email}`).waitFor();
  check("session survives a reload", true);

  const cookie = await sessionCookie();
  check("session cookie is set", Boolean(cookie));
  check("cookie is HttpOnly", cookie.httpOnly === true);
  check("cookie is SameSite=Lax", cookie.sameSite === "Lax");
  check(`cookie Secure is ${EXPECT_SECURE}`, cookie.secure === EXPECT_SECURE);
  const days = (cookie.expires - Date.now() / 1000) / 86400;
  check("cookie lasts 14 days", days > 13.9 && days < 14.1);

  const visible = await page.evaluate(() => ({
    cookie: document.cookie,
    local: JSON.stringify(localStorage),
    session: JSON.stringify(sessionStorage),
  }));
  check("page scripts cannot read the cookie", !visible.cookie.includes(COOKIE));
  check(
    "no token in localStorage or sessionStorage",
    !(visible.local + visible.session).includes(cookie.value),
  );

  await page.setViewportSize({ width: 375, height: 700 });
  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  check("no horizontal scroll at phone width", !overflows);

  for (const origin of ["https://evil.example", "null"]) {
    const response = await context.request.post(`${BASE}/api/auth/login`, {
      headers: { Origin: origin },
      data: { email, password },
    });
    const code = (await response.json()).error?.code;
    check(
      `login from Origin ${origin} is rejected`,
      response.status() === 403 && code === "origin_rejected",
    );
  }
  const noOrigin = await context.request.post(`${BASE}/api/auth/logout`);
  check("logout without an Origin is rejected", noOrigin.status() === 403);
  const still = await context.request.get(`${BASE}/api/auth/me`);
  check("rejected requests did not end the session", still.status() === 200);

  const replayOldCookie = () =>
    fetch(`${BASE}/api/auth/me`, { headers: { Cookie: `${COOKIE}=${cookie.value}` } });
  check("the cookie works outside the browser before sign out", (await replayOldCookie()).ok);

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(`${BASE}/login`);
  check("sign out opens the login page", true);
  check("sign out clears the cookie", !(await sessionCookie()));
  await page.goto(`${BASE}/account`);
  await page.waitForURL(`${BASE}/login`);
  check("account page redirects when signed out", true);

  check("replaying the old cookie gets 401", (await replayOldCookie()).status === 401);

  await submit(page, "/login", "Sign in");
  const second = await sessionCookie();
  check("signing in again issues a new token", Boolean(second) && second.value !== cookie.value);

  // A client must not be able to pick its own IP (needs uvicorn --no-proxy-headers).
  const statuses = [];
  for (let n = 1; n <= 6; n += 1) {
    const response = await context.request.post(`${BASE}/api/auth/login`, {
      headers: { Origin: BASE, "X-Forwarded-For": `192.0.2.${n}` },
      data: { email: `nobody-${email}`, password },
    });
    statuses.push(response.status());
  }
  check("a forged X-Forwarded-For does not dodge the limit", statuses.join() === "401,401,401,401,401,429");
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
