import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = fileURLToPath(new URL(".", import.meta.url));
const artifactDir = path.resolve(
  frontendDir,
  process.env.E2E_ARTIFACT_DIR || path.join(".e2e-artifacts", `run-${process.pid}`),
);
const authStatePath = path.join(artifactDir, "auth/user.json");
const testResultsDir = path.join(artifactDir, "test-results");
const reportDir = path.join(artifactDir, "playwright-report");
const frontendPort = Number(process.env.E2E_FRONTEND_PORT || "4018");
const backendPort = Number(process.env.E2E_BACKEND_PORT || "10106");
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const backendUrl = `http://127.0.0.1:${backendPort}`;

if (!process.env.DATABASE_URL) {
  throw new Error(
    "DATABASE_URL is required for Playwright E2E tests. Run ./run_e2e.sh from the repository root.",
  );
}

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  outputDir: testResultsDir,
  reporter: process.env.CI
    ? [["line"], ["html", { open: "never", outputFolder: reportDir }]]
    : [["list"], ["html", { open: "never", outputFolder: reportDir }]],
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  expect: {
    timeout: 8_000,
  },
  use: {
    baseURL: frontendUrl,
    storageState: authStatePath,
    timezoneId: "UTC",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: [
        "cd ../backend &&",
        "SECRET_KEY=e2e-test-secret-key-for-playwright-only",
        "ENCRYPTION_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        `FRONTEND_URL=${frontendUrl}`,
        `CORS_ORIGINS=${frontendUrl}`,
        "TIMEZONE=UTC",
        "TZ=UTC",
        "ALLOW_REGISTER=true",
        "PLAYWRIGHT_INSTALL_AT_STARTUP=false",
        "HEYM_PYTHON_TOOL_SANDBOX=subprocess",
        "HEYM_LLM_PRICING_SYNC_ENABLED=false",
        `uv run uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
      ].join(" "),
      url: `${backendUrl}/api/health`,
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      command: [
        `VITE_API_TARGET=${backendUrl}`,
        `node ./node_modules/vite/bin/vite.js --port ${frontendPort} --host 127.0.0.1`,
      ].join(" "),
      url: frontendUrl,
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
