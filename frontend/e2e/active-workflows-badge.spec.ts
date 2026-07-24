import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

interface ActiveExecutionFixture {
  execution_id: string;
  workflow_id: string;
  workflow_name: string;
  started_at: string;
  inputs: Record<string, unknown>;
  running_node_ids: string[];
  node_results: [];
}

function makeActiveExecution(
  index: number,
  workflowIndex = index,
): ActiveExecutionFixture {
  const suffix = String(index).padStart(12, "0");
  const workflowSuffix = String(workflowIndex).padStart(12, "0");
  return {
    execution_id: `10000000-0000-4000-8000-${suffix}`,
    workflow_id: `20000000-0000-4000-8000-${workflowSuffix}`,
    workflow_name: `Running workflow ${workflowIndex}`,
    started_at: new Date(Date.UTC(2026, 0, 1, 12, index)).toISOString(),
    inputs: {},
    running_node_ids: [`node-${index}`],
    node_results: [],
  };
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("polls, scrolls active workflows, and opens a live workflow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.install();

  const allActiveExecutions = Array.from({ length: 5 }, (_, index) =>
    makeActiveExecution(index + 1, index < 3 ? 1 : index + 1),
  );
  let activeExecutions = allActiveExecutions.slice(0, 2);
  let requestCount = 0;
  await page.route("**/api/workflows/executions/active", async (route) => {
    requestCount += 1;
    await route.fulfill({ json: activeExecutions });
  });

  await page.goto("/");

  const badge = page.getByTestId("active-workflows-badge");
  await expect(badge).toHaveText("2");
  await expect(badge).toHaveAttribute("aria-expanded", "false");
  expect(
    await badge.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return Math.abs(bounds.width - bounds.height) < 0.5;
    }),
  ).toBe(true);

  activeExecutions = allActiveExecutions;
  await page.clock.fastForward(10_000);
  await expect.poll(() => requestCount).toBeGreaterThanOrEqual(2);
  await expect(badge).toHaveText("5");

  await badge.click();
  const dropdown = page.getByTestId("active-workflows-dropdown");
  const scrollArea = page.getByTestId("active-workflows-scroll-area");
  await expect(dropdown).toBeVisible();
  await expect(dropdown.getByRole("menuitem")).toHaveCount(5);
  await expect(badge).toHaveAttribute("aria-expanded", "true");
  expect(
    await scrollArea.evaluate((element) => element.scrollHeight > element.clientHeight),
  ).toBe(true);

  await page
    .getByRole("menuitem", { name: "Open Running workflow 4 live view" })
    .click();
  await expect(page).toHaveURL(
    "/workflows/20000000-0000-4000-8000-000000000004/10000000-0000-4000-8000-000000000004",
  );
});

test("keeps the zero state non-interactive and hides the badge on mobile", async ({ page }) => {
  await page.route("**/api/workflows/executions/active", async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const counter = page.getByTestId("active-workflows-counter");
  await expect(counter).toHaveCSS("height", "0px");
  await expect(counter.getByRole("button")).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(counter).toHaveCount(0);
});

test("shows a non-interactive error badge when the initial refresh fails", async ({ page }) => {
  await page.route("**/api/workflows/executions/active", async (route) => {
    await route.fulfill({
      status: 503,
      json: { detail: "Active workflow status is temporarily unavailable" },
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const counter = page.getByTestId("active-workflows-counter");
  await expect(page.getByTestId("active-workflows-badge-error")).toBeVisible();
  await expect(counter.getByRole("button")).toHaveCount(0);
});
