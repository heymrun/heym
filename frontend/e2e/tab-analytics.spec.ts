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
  // Scoped to the KPI cards container: "Time Saved" is also a "Most Used
  // Workflows" table column header once that table has rows, which made this
  // locator ambiguous (strict-mode violation) depending on test run order.
  const kpiCards = page.getByTestId("analytics-kpi-cards");
  await expect(kpiCards.getByText("Time Saved")).toBeVisible();
  await expect(main.getByText("Chart selection is ready")).toBeVisible();
});

test("changes the time range and refetches metrics", async ({ page }) => {
  await page.goto("/?tab=analytics");
  await expect(page.getByRole("heading", { name: "Analytics Dashboard" })).toBeVisible();

  // The base window reflects the default 7d preset.
  await expect(page.getByText("Base window: 7d")).toBeVisible();
  const timeRange = page.locator('select:has(option[value="30d"])');
  await expect(timeRange.locator('option[value="1h"]')).toHaveText("Last Hour");

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

test("keeps the KPI captions on one line with the icon on the value row", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/?tab=analytics");
  const kpiCards = page.getByTestId("analytics-kpi-cards");
  const caption = kpiCards.getByText("Based on per-workflow estimates");
  await expect(caption).toBeVisible();
  expect(await caption.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
    true,
  );

  const timeSaved = kpiCards.getByTestId("analytics-kpi-card").filter({ hasText: "Time Saved" });
  const valueBox = await timeSaved.getByTestId("analytics-kpi-value").boundingBox();
  const iconBox = await timeSaved.getByTestId("analytics-kpi-icon").boundingBox();
  if (!valueBox || !iconBox) throw new Error("The Time Saved value or icon did not render");
  const valueCenter = valueBox.y + valueBox.height / 2;
  const iconCenter = iconBox.y + iconBox.height / 2;
  expect(Math.abs(valueCenter - iconCenter)).toBeLessThan(4);
});

test("renders the node type charts", async ({ page }) => {
  const nodesResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === "/api/analytics/nodes",
  );
  await page.goto("/?tab=analytics");
  expect((await nodesResponse).ok()).toBeTruthy();

  const section = page.getByTestId("analytics-node-types");
  await expect(section.getByRole("heading", { name: "Node Types" })).toBeVisible();
  await expect(section.getByText("Average Node Duration Over Time")).toBeVisible();
  for (const metric of ["duration", "errors", "calls"]) {
    await expect(section.getByTestId(`analytics-node-chart-${metric}`)).toBeVisible();
  }
});
