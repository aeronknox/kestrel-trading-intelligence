// Accessibility (axe, WCAG 2.1 A/AA) in both themes, plus horizontal overflow at phone width.
// Usage: npm run a11y [BASE=http://host:3000] [IGNORE_HTTPS_ERRORS=1]
// Exits non-zero on any critical/serious violation or any page that scrolls sideways at 390px.
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "playwright";

const BASE = process.env.BASE ?? "http://localhost:3000";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: process.env.IGNORE_HTTPS_ERRORS === "1" });
const page = await ctx.newPage();
const failures = [];
const notes = [];

async function settle(path) {
  await page.goto(`${BASE}${path}`);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1000);
}

async function axe(path, label) {
  await settle(path);
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  for (const v of r.violations) {
    const where = v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ");
    const line = `[${v.impact}] ${v.id} on ${label} ${path}: ${v.help} — ${where}`;
    (v.impact === "critical" || v.impact === "serious" ? failures : notes).push(line);
  }
}

async function overflow(path) {
  await settle(path);
  const o = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth }));
  if (o.scroll > o.width + 1) failures.push(`[overflow] ${path} scrolls sideways at ${o.width}px (content ${o.scroll}px wide)`);
}

const signedOut = ["/login", "/register", "/forgot-password"];
for (const p of signedOut) await axe(p, "signed-out");

// Sign in: a demo sandbox when available, otherwise a fresh account.
const config = await (await page.request.get(`${BASE}/api/v1/auth/config`)).json();
if (config.demo_enabled) {
  await page.goto(`${BASE}/login`);
  await page.getByRole("button", { name: "Try the demo" }).click();
} else {
  await page.goto(`${BASE}/register`);
  await page.fill("#name", "A11y Check");
  await page.fill("#email", `a11y${Date.now()}@example.com`);
  await page.fill("#password", "a11y-passw0rd-1");
  await page.click("button[type=submit]");
}
await page.waitForURL("**/dashboard", { timeout: 60000 });

const api = async (p) => (await page.request.get(`${BASE}/api/v1${p}`)).json();
let strategies = await api("/strategies");
if (!strategies.length) {
  const tpl = (await api("/strategies/templates")).templates[0];
  await page.request.post(`${BASE}/api/v1/strategies`, { data: { name: "A11y", config: { symbol: "BTC-USD", timeframe: "1h", ...tpl.definition } } });
  strategies = await api("/strategies");
}
const sid = strategies[0].id;
let backtests = await api("/backtests");
if (!backtests.length) {
  await page.request.post(`${BASE}/api/v1/backtests`, { data: { strategy_id: sid, bars: 500 }, timeout: 120000 });
  backtests = await api("/backtests");
}
const sweep = await (await page.request.post(`${BASE}/api/v1/research/sweeps`, {
  data: { strategy_id: sid, bars: 600, params: [{ path: "risk.stop_loss_pct", values: [2, 4, 6] }], min_trades: 0 }, timeout: 120000,
})).json();

const pages = ["/dashboard", "/markets", "/markets/BTC-USD", "/analysis", "/assistant", "/strategies", `/strategies/${sid}`,
  "/strategies/new", "/backtests", `/backtests/${backtests[0].id}`, "/research", "/research/new", `/research/${sweep.id}`,
  "/alerts", "/paper-trading", "/portfolio", "/settings"];

for (const theme of ["dark", "light"]) {
  await page.evaluate((t) => localStorage.setItem("ti-theme", t), theme);
  for (const p of pages) await axe(p, theme);
}

await page.setViewportSize({ width: 390, height: 844 });
await page.evaluate(() => localStorage.setItem("ti-theme", "dark"));
for (const p of pages) await overflow(p);

console.log(`Checked ${signedOut.length + pages.length * 2} page/theme combinations with axe and ${pages.length} pages at 390px.`);
if (notes.length) console.log("\nMinor/moderate findings (not failing):\n" + notes.join("\n"));
console.log(failures.length ? "\nFAILURES:\n" + failures.join("\n") : "\nA11Y_OK");
await browser.close();
process.exit(failures.length ? 1 : 0);
