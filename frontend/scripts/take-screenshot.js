const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

(async () => {
  const url = process.env.SCREENSHOT_URL || "http://localhost:4017/_screenshot-debug";
  const outDir = path.resolve(__dirname, ".e2e-artifacts");
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, "json-viewer-toggle-after.png");

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();

  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });
    await page.waitForSelector('[data-testid="debug-node-result-build_json"]', { timeout: 10_000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: outPath, fullPage: false });
    console.log(`Screenshot saved to ${outPath}`);
  } catch (error) {
    console.error("Screenshot failed:", error);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
