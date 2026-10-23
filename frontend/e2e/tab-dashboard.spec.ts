import { expect, test } from "@playwright/test";

import {
  clearDashboardWidgets,
  createDashboardWidget,
  createWorkflow,
  deleteDashboardWidget,
  deleteWorkflow,
  expectOk,
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
      /^\/api\/dashboards\/[0-9a-f-]+\/widgets$/.test(new URL(response.url()).pathname),
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
  await expect(header.getByTestId("dashboard-select")).toBeVisible();
  await expect(header.getByRole("button", { name: "Refresh dashboard" })).toBeVisible();
  await expect(header.getByRole("button", { name: "Add widget" })).toBeVisible();

  const hasHorizontalOverflow = await header.evaluate(
    (element) => element.scrollWidth > element.clientWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});

test("narrows a HITL widget to one workflow's reviews from Settings", async ({ page }) => {
  await clearDashboardWidgets(page);
  const stamp = Date.now();
  const reviewAgent = (label: string): Record<string, unknown> => ({
    id: `agent-${stamp}`,
    type: "agent",
    position: { x: 0, y: 0 },
    data: { label, hitlEnabled: true },
  });
  const invoices = await createWorkflow(page, `E2E Invoices ${stamp}`, [reviewAgent("Approver")]);
  const hiring = await createWorkflow(page, `E2E Hiring ${stamp}`, [reviewAgent("Screener")]);
  const widget = await createDashboardWidget(page, `E2E Reviews ${stamp}`, "hitl");
  // A waiting review keeps its workflow from being deleted, so cleanup cancels these runs first.
  const waitingRuns: { workflowId: string; executionId: string }[] = [];

  try {
    for (const [workflow, draft] of [
      [invoices, "Pay invoice 42"],
      [hiring, "Invite candidate 7"],
    ] as const) {
      const seeded = await page.request.post(`/api/workflows/${workflow.id}/pending-review`, {
        data: { summary: draft, draft_text: draft },
      });
      await expectOk(seeded);
      const { execution_history_id: executionId } = (await seeded.json()) as {
        execution_history_id: string;
      };
      waitingRuns.push({ workflowId: workflow.id, executionId });
    }

    await page.goto("/?tab=dashboard");
    await expect(page.getByText(`E2E Reviews ${stamp}`)).toBeVisible();

    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Widget settings" })).toBeVisible();
    await page
      .getByTestId("hitl-filter-workflow")
      .locator("select")
      .selectOption({ label: invoices.name });
    // The workflow has one review step, so it is picked with it.
    await expect(page.getByTestId("hitl-filter-step").locator("select")).toHaveValue(
      `agent-${stamp}`,
    );
    const openWorkflow = page.getByRole("link", { name: "Open workflow in a new tab" });
    await expect(openWorkflow).toHaveAttribute("href", `/workflows/${invoices.id}`);
    await expect(openWorkflow).toHaveAttribute("target", "_blank");

    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        new URL(response.url()).pathname === `/api/dashboards/widgets/${widget.id}`,
    );
    await page.getByRole("button", { name: "Save" }).click();
    expect((await saved).ok()).toBeTruthy();

    // The card names the review's workflow as "<name> · <step>"; the quick workflow list on
    // the page names both workflows too, so match the card's button only.
    const reviewOf = (name: string): RegExp => new RegExp(`^${name} ·`);
    await expect(page.getByText("1/1 pending")).toBeVisible();
    await expect(page.getByRole("button", { name: reviewOf(invoices.name) })).toBeVisible();
    await expect(page.getByRole("button", { name: reviewOf(hiring.name) })).toHaveCount(0);
  } finally {
    await deleteDashboardWidget(page, widget.id);
    for (const run of waitingRuns) {
      await page.request.post(
        `/api/workflows/${run.workflowId}/executions/${run.executionId}/cancel`,
      );
    }
    await deleteWorkflow(page, invoices.id);
    await deleteWorkflow(page, hiring.id);
  }
});
