import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = fileURLToPath(new URL(".", import.meta.url));
const authStatePath = path.join(frontendDir, "e2e/.auth/user.json");
const frontendPort = Number(process.env.E2E_FRONTEND_PORT || "4018");
const backendPort = Number(process.env.E2E_BACKEND_PORT || "10106");
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const backendUrl = `http://127.0.0.1:${backendPort}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["line"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  expect: {
    timeout: 8_000,
  },
  use: {
    baseURL: frontendUrl,
    storageState: authStatePath,
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
        "ALLOW_REGISTER=true",
        "PLAYWRIGHT_INSTALL_AT_STARTUP=false",
        "HEYM_PYTHON_TOOL_SANDBOX=subprocess",
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
