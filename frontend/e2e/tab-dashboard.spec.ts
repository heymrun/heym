import { expect, test } from "@playwright/test";

import {
  clearDashboardWidgets,
  createDashboardWidget,
  deleteDashboardWidget,
  deleteWorkflow,
  prepareAuthenticatedPage,
} from "./support";

// These tests share one account's dashboard and assert on its global empty
// state, so they must not run concurrently with each other under --fully-parallel.
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("creates a widget via the Add widget dialog and opens the editor", async ({ page }) => {
  await clearDashboardWidgets(page);

  await page.goto("/?tab=dashboard");
  await expect(page.getByText("No widgets yet.")).toBeVisible();

  // Open the Add widget dialog from the header action (the empty state also
  // exposes an "Add widget" button, so scope to the header).
  await page.getByTestId("dashboard-header").getByRole("button", { name: "Add widget" }).click();
  await expect(page.getByRole("heading", { name: "Add widget" })).toBeVisible();

  // Submitting creates the widget (+ backing workflow) and opens the editor.
  const widgetResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/dashboards/widgets",
  );
  await page.getByRole("button", { name: "Create & edit" }).click();
  const widget = (await (await widgetResponsePromise).json()) as {
    id: string;
    workflow_id: string;
  };

  try {
    await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]+$/);
  } finally {
    await deleteDashboardWidget(page, widget.id);
    await deleteWorkflow(page, widget.workflow_id);
  }
});

test("renders a seeded widget, toggles edit mode, and refreshes", async ({ page }) => {
  await clearDashboardWidgets(page);
  const widgetTitle = `E2E Widget ${Date.now()}`;
  const widget = await createDashboardWidget(page, widgetTitle);

  try {
    await page.goto("/?tab=dashboard");

    // The seeded widget renders with its title on the grid.
    await expect(page.getByText(widgetTitle)).toBeVisible();

    // Edit mode toggles the action's accessible name and visible label.
    const editButton = page.getByRole("button", { name: "Edit dashboard" });
    await expect(editButton).toBeVisible();
    await editButton.click();
    await expect(page.getByRole("button", { name: "Finish editing dashboard" })).toBeVisible();

    // The refresh action is always available.
    await page.getByRole("button", { name: "Finish editing dashboard" }).click();
    await expect(page.getByRole("button", { name: "Refresh dashboard" })).toBeVisible();
  } finally {
    await deleteDashboardWidget(page, widget.id);
    await deleteWorkflow(page, widget.workflow_id);
  }
});

test("keeps the dashboard header within a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?tab=dashboard");

  const header = page.getByTestId("dashboard-header");
  await expect(header.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(header.getByRole("button", { name: "Refresh dashboard" })).toBeVisible();
  await expect(header.getByRole("button", { name: "Add widget" })).toBeVisible();

  const hasHorizontalOverflow = await header.evaluate(
    (element) => element.scrollWidth > element.clientWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});
