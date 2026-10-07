// UI smoke test: opens every workspace screen against a running backend and
// fails if a screen shows an error, renders nothing, or logs a page error.
//
// One-time setup (not part of `npm ci`, so normal installs stay small):
//   npm i --no-save playwright && npx playwright install chromium
// Run (backend serving the built UI with data loaded, e.g. after `python pipeline.py demo`):
//   uvicorn evostrategy_backend.main:app --port 8000
//   node smoke-test.mjs [http://127.0.0.1:8000]

import { chromium } from "playwright";

const base = process.argv[2] ?? "http://127.0.0.1:8000";
const screens = ["Overview", "Review queue", "Documents", "Audit log", "Analytics", "Forecast",
  "Cash runway", "What-if", "Evaluation", "Settings"];

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const problems = [];
page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));

await page.goto(base);
await page.waitForTimeout(1500);
if (!(await page.getByRole("button", { name: /^Overview/ }).count())) {
  console.error("Workspace not shown — load data first (python pipeline.py demo).");
  process.exit(2);
}
for (const name of screens) {
  await page.getByRole("button", { name: new RegExp(`^${name}`) }).first().click();
  await page.waitForTimeout(name === "Forecast" || name === "What-if" ? 6000 : 2000);
  const main = page.locator(".workspace-main");
  const text = await main.innerText();
  const errors = await main.locator(".notice.error").count();
  const ok = text.length > 120 && errors === 0 && !text.includes("Loading…");
  console.log(`${ok ? "ok  " : "FAIL"} ${name}`);
  if (!ok) problems.push(`${name}: ${errors ? "error notice shown" : "screen empty or still loading"}`);
}
await browser.close();
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log("All screens rendered.");
