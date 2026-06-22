import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows a cron workflow on the calendar and removes it after deletion", async ({ page }) => {
  const workflow = await createWorkflow(page, `Scheduled Workflow ${Date.now()}`, [
    {
      id: "cron-1",
      type: "cron",
      position: { x: 100, y: 100 },
      data: { label: "cron", cronExpression: "0 12 * * 3" },
    },
  ]);

  try {
    await page.goto("/?tab=schedules");
    await expect(page.getByRole("button", { name: "This Week" })).toBeVisible();
    await expect(page.getByText(workflow.name).first()).toBeVisible();

    await deleteWorkflow(page, workflow.id);
    await page.reload();
    await expect(page.getByText(workflow.name)).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("switches calendar views and toggles the shared filter", async ({ page }) => {
  await page.goto("/?tab=schedules");

  // Default view is the week view.
  await expect(page.getByRole("button", { name: "This Week" })).toBeVisible();

  // Switching to the month view updates the "today" anchor button label.
  await page.getByRole("button", { name: "month", exact: true }).click();
  await expect(page.getByRole("button", { name: "This Month" })).toBeVisible();

  // Switching to the day view updates the label again.
  await page.getByRole("button", { name: "day", exact: true }).click();
  await expect(page.getByRole("button", { name: "Today", exact: true })).toBeVisible();

  // The "shared with me" filter is an independent toggle (on by default).
  const sharedToggle = page.getByRole("checkbox");
  await expect(sharedToggle).toBeChecked();
  await page.getByText("Show shared with me").click();
  await expect(sharedToggle).not.toBeChecked();
});
