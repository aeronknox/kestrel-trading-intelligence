// End-to-end UI flows against a running stack (frontend :3000 + backend :8000).
// Usage: npm run e2e  [BASE=http://host:3000] [IGNORE_HTTPS_ERRORS=1]   Exits non-zero if any step fails.
import { readFile } from "node:fs/promises";

import { chromium } from "playwright";

const BASE = process.env.BASE ?? "http://localhost:3000";
const email = `audit${Date.now()}@example.com`;
const results = [];
const errors = [];
const started = Date.now();

/** On GitHub Actions, failures become annotations: readable on the run page without signing in. */
function annotate(title, text) {
  if (!process.env.GITHUB_ACTIONS) return;
  console.log(`::error title=${title}::${String(text).replace(/\r?\n/g, " ").replace(/%/g, "%25").slice(0, 900)}`);
}
// A crash part-way through must still say what had failed so far.
for (const event of ["uncaughtException", "unhandledRejection"]) {
  process.on(event, (e) => {
    annotate("Browser flows crashed", `${e?.stack ?? e} | results so far: ${results.join(", ")}`);
    process.exit(1);
  });
}

const browser = await chromium.launch();
// IGNORE_HTTPS_ERRORS=1 accepts the self-signed certificate of a local HTTPS trial (Caddy with DOMAIN=localhost).
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: process.env.IGNORE_HTTPS_ERRORS === "1" });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push(`[pageerror] ${page.url()} ${e.message}`));
// Statuses a step deliberately provokes (e.g. a bad link -> 422); 401 is the normal signed-out probe.
let expectedStatuses = [];
page.on("console", (m) => {
  const text = m.text();
  if (m.type() !== "error" || text.includes("401") || expectedStatuses.some((s) => text.includes(`status of ${s}`))) return;
  errors.push(`[console] ${page.url()} ${text}`);
});

/** Click a download link and return the downloaded file's text (BOM stripped). */
async function download(locator) {
  const [file] = await Promise.all([page.waitForEvent("download"), locator.click()]);
  if (!file.suggestedFilename().endsWith(".csv")) throw new Error(`unexpected file ${file.suggestedFilename()}`);
  return (await readFile(await file.path(), "utf8")).replace(/^\ufeff/, "");
}

async function step(name, fn) {
  try {
    await fn();
    results.push(`PASS ${name}`);
  } catch (e) {
    results.push(`FAIL ${name}: ${String(e.message).split("\n")[0]}`);
    annotate("Browser flow failed", `${name} at ${page.url()} after ${Math.round((Date.now() - started) / 1000)}s: ${e.message}`);
    await page.screenshot({ path: `e2e/fail_${name.replace(/\W+/g, "_")}.png` }).catch(() => {});
  }
}
const toast = (re) => page.locator("[data-sonner-toast]").filter({ hasText: re }).first().waitFor({ timeout: 20000 });

await step("register", async () => {
  await page.goto(`${BASE}/register`);
  await page.fill("#name", "Audit User");
  await page.fill("#email", email);
  await page.fill("#password", "audit-passw0rd1");
  await page.click("button[type=submit]");
  await page.waitForURL("**/dashboard", { timeout: 15000 });
  await page.getByText("Virtual portfolio value").waitFor();
});

await step("unverified email banner resends link", async () => {
  await page.getByText("Confirm your email address").waitFor();
  await page.getByRole("button", { name: "Resend email" }).click();
  await toast(/Verification email sent to/);
  await page.getByRole("button", { name: "Email sent" }).waitFor();
});

await step("unauthenticated redirect after logout+login cycle", async () => {
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByText("Sign out").click();
  await page.waitForURL("**/login");
  await page.goto(`${BASE}/dashboard`);
  await page.waitForURL("**/login", { timeout: 10000 });
  await page.fill("#email", email);
  await page.fill("#password", "audit-passw0rd1");
  await page.click("button[type=submit]");
  await page.waitForURL("**/dashboard");
});

await step("dashboard run AI analysis button", async () => {
  await page.getByRole("button", { name: /Run AI analysis/ }).click();
  await toast(/Analysis complete/);
});

await step("markets watchlist star toggle", async () => {
  await page.goto(`${BASE}/markets`);
  await page.getByLabel("Add DOT-USD to watchlist").click();
  await toast(/DOT-USD added/);
  await page.getByLabel("Remove DOT-USD from watchlist").click();
  await toast(/DOT-USD removed/);
});

await step("markets track-asset catalog search", async () => {
  await page.getByRole("button", { name: /Track asset/ }).click();
  await page.getByPlaceholder(/ATOM/).fill("ATOM");
  await page.getByRole("dialog").getByText("ATOM-USD", { exact: true }).first().waitFor({ timeout: 20000 });
  await page.keyboard.press("Escape");
});

await step("asset detail timeframe + overlay toggles", async () => {
  await page.goto(`${BASE}/markets/ETH-USD`);
  await page.getByRole("radio", { name: "15m" }).click();
  await page.getByRole("button", { name: "MACD" }).click();
  await page.waitForTimeout(2500);
  if ((await page.locator("canvas").count()) < 2) throw new Error("chart canvas missing");
});

await step("header asset search navigates", async () => {
  await page.getByLabel("Search assets").fill("sol");
  await page.getByRole("button", { name: /SOL-USD/ }).first().click();
  await page.waitForURL("**/markets/SOL-USD");
});

await step("analysis page run + history", async () => {
  await page.goto(`${BASE}/analysis?symbol=SOL-USD&timeframe=1h`);
  await page.getByRole("button", { name: /Run analysis/ }).first().click();
  await page.getByText("Why this signal").waitFor({ timeout: 30000 });
  await page.getByText("Signal history").waitFor();
});

await step("strategy create from template via UI", async () => {
  await page.goto(`${BASE}/strategies`);
  await page.getByRole("link", { name: /MACD momentum/ }).click();
  await page.waitForURL("**/strategies/new?template=macd_momentum");
  await page.getByRole("button", { name: /Create strategy/ }).click();
  await page.waitForURL(/\/strategies\/\d+$/, { timeout: 15000 });
});

await step("strategy edit adds condition and saves new version", async () => {
  await page.getByRole("button", { name: /Add condition/ }).first().click();
  await page.getByRole("button", { name: /Save new version/ }).click();
  await toast(/Saved as version 2/);
});

await step("strategy validation blocks zero stop-loss", async () => {
  const stop = page.getByLabel(/Stop-loss/);
  await stop.fill("0");
  await page.getByRole("button", { name: /Save new version/ }).click();
  await page.waitForTimeout(1500);
  const bad = await page.locator("[data-sonner-toast]").filter({ hasText: /stop_loss|greater than/i }).count();
  if (bad) throw new Error("server rejected 0 with a 422 instead of treating it as 'off'");
});

await step("strategy alerts switch on and are listed", async () => {
  const url = page.url(); // still on the strategy page
  await page.getByLabel("Alerts on").click();
  await toast(/Alerts on/);
  await page.getByText("Watching").waitFor();
  await page.getByRole("switch", { name: "Auto paper-trade" }).click();
  await toast(/Forward test on/);
  await page.getByRole("button", { name: /^Alerts/ }).click(); // header bell
  await page.getByText("Strategy alerts").waitFor();
  await page.keyboard.press("Escape");
  await page.goto(`${BASE}/alerts`);
  await page.getByText("Watched strategies").waitFor();
  await page.getByRole("cell", { name: "On", exact: true }).first().waitFor();
  await page.goto(url);
  await page.getByText("Watching").waitFor(); // persisted
});

await step("run backtest from dialog", async () => {
  await page.goto(page.url());
  await page.getByRole("button", { name: /^Backtest$/ }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: /Run backtest/ }).click();
  await page.waitForURL(/\/backtests\/\d+$/, { timeout: 30000 });
  await page.getByText("Equity curve").waitFor();
});

await step("backtest compare flow", async () => {
  await page.goto(`${BASE}/strategies`);
  await page.getByRole("link", { name: /RSI mean reversion/ }).click();
  await page.waitForURL("**/strategies/new?template=rsi_mean_reversion");
  await page.getByRole("button", { name: /Create strategy/ }).click();
  await page.waitForURL(/\/strategies\/\d+$/);
  await page.getByRole("button", { name: /^Backtest$/ }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: /Run backtest/ }).click();
  await page.waitForURL(/\/backtests\/\d+$/, { timeout: 30000 });
  await page.goto(`${BASE}/backtests`);
  const boxes = page.locator("input[type=checkbox]:not([disabled])");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await page.getByRole("button", { name: /Compare/ }).click();
  await page.waitForURL("**/backtests/compare?ids=*");
  await page.getByText("Cumulative return").waitFor();
});

await step("backtest CSV export", async () => {
  await page.goto(`${BASE}/backtests`);
  await page.locator('a[href^="/backtests/"]').filter({ hasNotText: /compare/i }).first().click();
  await page.waitForURL(/\/backtests\/\d+$/);
  const csv = await download(page.getByRole("link", { name: "Download Trades CSV" }));
  if (!csv.startsWith("entry_time,entry_price,quantity")) throw new Error(`bad header: ${csv.slice(0, 60)}`);
  const equity = await download(page.getByRole("link", { name: "Download Equity CSV" }));
  if (equity.trim().split("\n").length < 50) throw new Error("equity CSV too short");
});

await step("short strategy backtest", async () => {
  await page.goto(`${BASE}/strategies/new?template=rsi_mean_reversion`);
  await page.getByLabel("Name").fill(`Short RSI ${Date.now()}`);
  await page.getByRole("combobox", { name: "Direction" }).click();
  await page.getByRole("option", { name: /Short/ }).click();
  await page.getByText("Enter short when").waitFor();
  await page.getByRole("button", { name: /Create strategy/ }).click();
  await page.waitForURL(/\/strategies\/\d+$/, { timeout: 15000 });
  await page.getByRole("button", { name: /^Backtest$/ }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: /Run backtest/ }).click();
  await page.waitForURL(/\/backtests\/\d+$/, { timeout: 30000 });
  await page.getByText(/short: sells at entry/).waitFor();
});

await step("multi-asset test", async () => {
  await page.goto(`${BASE}/research/new`);
  await page.getByRole("radio", { name: "Multi-asset test" }).click();
  await page.getByText(/of 2–6 selected/).waitFor();
  await page.getByRole("button", { name: "Run multi-asset test" }).click();
  await page.waitForURL(/\/research\/\d+$/, { timeout: 60000 });
  await page.getByText("Portfolio equity").waitFor({ timeout: 15000 });
  await page.getByText("Price correlation").waitFor();
  if ((await page.getByRole("row").count()) < 4) throw new Error("per-asset table missing rows");
});

await step("walk-forward test via optimization page", async () => {
  await page.goto(`${BASE}/research/new`);
  await page.getByText("Parameter 1").waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: "Run walk-forward test" }).click();
  await page.waitForURL(/\/research\/\d+$/, { timeout: 60000 });
  await page.getByText("Out-of-sample equity").waitFor({ timeout: 15000 });
  await page.getByRole("cell", { name: "1", exact: true }).first().waitFor();
});

await step("parameter sweep heatmap", async () => {
  await page.goto(`${BASE}/research/new`);
  await page.getByRole("radio", { name: "Parameter sweep" }).click();
  await page.getByRole("button", { name: /Add a second parameter/ }).click();
  await page.getByText("Parameter 2").waitFor();
  await page.getByRole("button", { name: "Run sweep" }).click();
  await page.waitForURL(/\/research\/\d+$/, { timeout: 60000 });
  await page.getByText("Results grid").waitFor({ timeout: 15000 });
  await page.getByRole("radio", { name: "Drawdown" }).click();
  await page.goto(`${BASE}/research`);
  await page.getByRole("cell", { name: "Sweep", exact: true }).first().waitFor({ timeout: 15000 });
  await page.getByRole("cell", { name: "Walk-forward", exact: true }).first().waitFor();
});

await step("paper market buy via ticket", async () => {
  await page.goto(`${BASE}/paper-trading?symbol=ETH-USD`);
  await page.getByPlaceholder("0.00").fill("1000");
  await page.getByRole("button", { name: /Buy ETH \(paper\)/ }).click();
  await toast(/Filled: buy/);
  await page.getByRole("button", { name: "Close" }).first().waitFor();
});

await step("paper limit order + cancel", async () => {
  await page.getByRole("radio", { name: "Limit" }).click();
  await page.getByLabel(/Limit price/).fill("1");
  await page.getByPlaceholder("0.00").fill("50");
  await page.getByRole("button", { name: /Buy ETH \(paper\)/ }).click();
  await toast(/Limit order placed/);
  await page.getByLabel("Cancel order").first().click();
  await toast(/Order cancelled/);
});

await step("paper close position", async () => {
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Close" }).first().click();
  await toast(/Closed ETH-USD/);
});

await step("paper trades CSV export", async () => {
  await page.goto(`${BASE}/paper-trading`);
  const csv = await download(page.getByRole("link", { name: "Download Trades CSV" }));
  const lines = csv.trim().split("\n");
  if (!lines[0].startsWith("executed_at,symbol,side") || lines.length < 3) throw new Error(`unexpected CSV: ${lines.length} lines`);
});

await step("paper short sale and cover", async () => {
  await page.goto(`${BASE}/paper-trading?symbol=SOL-USD`);
  await page.getByRole("button", { name: /Risk limits/ }).click();
  await page.getByRole("switch", { name: "Allow short selling" }).click();
  await page.getByRole("button", { name: "Save limits" }).click();
  await toast(/Risk limits updated/);
  await page.getByRole("button", { name: "Sell", exact: true }).click();
  await page.getByPlaceholder("0.00").fill("500");
  await page.getByRole("button", { name: /Sell short SOL \(paper\)/ }).click();
  await toast(/Filled: sell/);
  await page.getByText("Short", { exact: true }).first().waitFor();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Cover" }).first().click();
  await toast(/Closed SOL/);
});

await step("risk limits dialog saves", async () => {
  await page.getByRole("button", { name: /Risk limits/ }).click();
  await page.getByLabel(/Max open positions/).fill("5");
  await page.getByRole("button", { name: /Save limits/ }).click();
  await toast(/Risk limits updated/);
});

await step("portfolio page renders analytics", async () => {
  await page.goto(`${BASE}/portfolio`);
  await page.getByText("Equity history").waitFor();
  await page.getByText("Trade statistics").waitFor();
});

await step("assistant chat answers", async () => {
  await page.goto(`${BASE}/assistant`);
  await page.getByRole("button", { name: "Compare BTC vs SOL" }).click();
  await page.getByText(/Comparison/).waitFor({ timeout: 30000 });
  await page.getByLabel("Message").fill("How is my portfolio doing?");
  await page.keyboard.press("Enter");
  await page.getByText(/Your simulated portfolio/).waitFor({ timeout: 30000 });
});

await step("settings save preferences", async () => {
  await page.goto(`${BASE}/settings`);
  await page.getByRole("button", { name: /Save preferences/ }).click();
  await toast(/Preferences saved/);
});

await step("non-admin blocked from admin page", async () => {
  await page.goto(`${BASE}/admin`);
  await page.getByText("Administrator access required").waitFor();
});

await step("theme toggle", async () => {
  await page.getByLabel("Toggle theme").click();
  const cls = await page.evaluate(() => document.documentElement.className);
  if (!cls.includes("light")) throw new Error("light class not applied");
  await page.getByLabel("Toggle theme").click();
});

await step("expired session redirects to login", async () => {
  await page.goto(`${BASE}/dashboard`);
  await page.getByText("Virtual portfolio value").waitFor();
  await ctx.clearCookies(); // simulate server-side expiry/revocation
  await page.getByRole("link", { name: "Portfolio" }).first().click();
  await page.waitForURL("**/login", { timeout: 10000 });
});

await step("forgot password request", async () => {
  await page.goto(`${BASE}/login`);
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await page.waitForURL("**/forgot-password");
  await page.fill("#email", email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await page.getByText("Check your email").waitFor();
  await page.getByText(/If an account exists/).waitFor();
});

await step("invalid reset and verification links are explained", async () => {
  expectedStatuses = [422];
  await page.goto(`${BASE}/reset-password?token=not-a-real-token-0123456789`);
  await page.fill("#password", "brand-new-passw0rd1");
  if (page.url().includes("token=")) throw new Error("token left in the address bar");
  await page.fill("#confirm", "brand-new-passw0rd1");
  await page.getByRole("button", { name: "Update password" }).click();
  await page.getByText(/invalid or has expired/).waitFor();
  await page.goto(`${BASE}/verify-email?token=not-a-real-token-0123456789`);
  await page.getByText("We couldn't verify your email").waitFor();
  expectedStatuses = [];
});

await step("content security policy blocks injected scripts", async () => {
  const resp = await page.goto(`${BASE}/login`);
  const csp = (await resp.headers())["content-security-policy"] ?? "";
  const nonce = /'nonce-([^']+)'/.exec(csp)?.[1];
  if (!nonce || /script-src[^;]*unsafe-inline/.test(csp)) throw new Error(`weak or missing CSP: ${csp}`);
  // Every script the server rendered carries this request's nonce...
  const unsigned = await page.locator("script").evaluateAll((els, n) => els.filter((e) => e.nonce !== n).length, nonce);
  if (unsigned) throw new Error(`${unsigned} scripts without the page nonce`);
  // ...and markup injected the way an XSS payload would be cannot run code.
  const before = errors.length;
  await page.evaluate(() => document.body.insertAdjacentHTML("beforeend", '<img src="data:," onerror="window.__xss = 1">'));
  await page.waitForTimeout(500);
  if (await page.evaluate(() => window.__xss)) throw new Error("injected inline handler ran");
  errors.splice(before).filter((e) => !/Content Security Policy/.test(e)).forEach((e) => errors.push(e)); // the blocked handler is expected
});

await step("demo sandbox (when DEMO_MODE is on)", async () => {
  const config = await (await page.request.get(`${BASE}/api/v1/auth/config`)).json();
  if (!config.demo_enabled) return; // the button only exists on demo deployments
  await ctx.clearCookies();
  await page.goto(`${BASE}/login`);
  await page.getByRole("button", { name: "Try the demo" }).click();
  await page.waitForURL("**/dashboard", { timeout: 30000 });
  await page.getByText("demo sandbox").waitFor();
  await page.goto(`${BASE}/strategies`);
  await page.getByText("RSI mean reversion").first().waitFor();
  await page.getByText("Moving-average crossover").first().waitFor();
  await page.goto(`${BASE}/settings`);
  await page.getByText("Preferences").first().waitFor();
  if (await page.getByText("Change password").count()) throw new Error("password form shown in the demo");
  await page.getByRole("button", { name: "Create a free account" }).click();
  await page.waitForURL("**/register");
});

console.log(results.join("\n"));
console.log(errors.length ? "\nBROWSER ERRORS:\n" + [...new Set(errors)].join("\n") : "\nNO_BROWSER_ERRORS");
// On GitHub Actions, failures also become annotations, readable on the run page without signing in.
for (const e of [...new Set(errors)].slice(0, 8)) annotate("Browser error", e);
await browser.close();
process.exit(results.some((r) => r.startsWith("FAIL")) || errors.length ? 1 : 0);
