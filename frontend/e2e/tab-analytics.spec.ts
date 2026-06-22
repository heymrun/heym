import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("renders the analytics dashboard with KPI cards", async ({ page }) => {
  await page.goto("/?tab=analytics");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Analytics Dashboard" })).toBeVisible();
  await expect(main.getByText("Total Executions")).toBeVisible();
  await expect(main.getByText("Chart selection is ready")).toBeVisible();
});

test("changes the time range and refetches metrics", async ({ page }) => {
  await page.goto("/?tab=analytics");
  await expect(page.getByRole("heading", { name: "Analytics Dashboard" })).toBeVisible();

  // The base window reflects the default 7d preset.
  await expect(page.getByText("Base window: 7d")).toBeVisible();

  // Switching the preset updates the window and refetches metrics.
  const metricsPromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === "/api/analytics/metrics",
  );
  await page.locator('select:has(option[value="30d"])').selectOption("30d");
  expect((await metricsPromise).ok()).toBeTruthy();
  await expect(page.getByText("Base window: 30d")).toBeVisible();
});
