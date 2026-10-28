import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

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
  await expect(timeRange.locator('option[value="3h"]')).toHaveText("Last 3 Hours");
  await expect(timeRange.locator('option[value="6h"]')).toHaveText("Last 6 Hours");

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

test("shows a loading badge after a range change until the data arrives", async ({ page }) => {
  await page.goto("/?tab=analytics");
  await expect(page.getByTestId("analytics-kpi-cards")).toBeVisible();
  const loading = page.getByTestId("analytics-loading");
  await expect(loading).toBeHidden();

  // Hold the node rankings back so the reload is still in flight when we look.
  let releaseNodes: () => void = () => {};
  const nodesHeld = new Promise<void>((resolve) => {
    releaseNodes = resolve;
  });
  await page.route("**/api/analytics/nodes**", async (route) => {
    await nodesHeld;
    await route.continue();
  });

  await page.locator('select:has(option[value="6h"])').selectOption("6h");
  await expect(loading).toBeVisible();
  await expect(loading).toContainText("Loading analytics...");

  releaseNodes();
  await expect(loading).toBeHidden();
  await expect(page.getByText("Base window: 6h")).toBeVisible();
});

test("a click on a chart is not a range, a drag over two points is", async ({ page }) => {
  // The series only render once the user can see a workflow.
  const workflow = await createWorkflow(page, `Analytics Selection ${Date.now()}`);
  await page.goto("/?tab=analytics");
  await page.locator('select:has(option[value="3h"])').selectOption("3h");
  await expect(page.getByText("Base window: 3h")).toBeVisible();

  const volume = page
    .locator("div.p-4")
    .filter({ has: page.locator(".apexcharts-title-text", { hasText: "Execution Volume Over Time" }) })
    .last();
  const grid = await volume.locator(".apexcharts-grid").boundingBox();
  if (!grid) throw new Error("The execution volume chart did not render");

  // 3h has four hourly points across the chart: a short drag between two of them selects none.
  const drag = async (from: number, to: number): Promise<void> => {
    await page.mouse.move(grid.x + grid.width * from, grid.y + grid.height / 2);
    await page.mouse.down();
    await page.mouse.move(grid.x + grid.width * to, grid.y + grid.height / 2 + 15, { steps: 6 });
    await page.mouse.up();
  };

  await drag(0.1, 0.2);
  await page.waitForTimeout(500);
  await expect(page.getByText("Chart selection is ready")).toBeVisible();

  await drag(0.05, 0.72);
  await expect(page.getByText("Selection mode is active")).toBeVisible();

  await deleteWorkflow(page, workflow.id);
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
  await expect(section.getByRole("heading", { name: "Node Types", exact: true })).toBeVisible();
  for (const title of [
    "Most Time Taken Nodes",
    "Most Failed Node Types",
    "Most Called Node Types",
  ]) {
    await expect(section.getByRole("heading", { name: title })).toBeVisible();
  }
  for (const metric of ["duration", "errors", "calls"]) {
    await expect(section.getByTestId(`analytics-node-chart-${metric}`)).toBeVisible();
  }
});
