import { test, expect } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

/** Simulate a second tab / another user saving the workflow. */
async function saveFromElsewhere(
  page: import("@playwright/test").Page,
  id: string,
  previousUpdatedAt?: string | null,
): Promise<string> {
  const response = await page.request.put(`/api/workflows/${id}`, {
    data: {
      nodes: [
        {
          id: "other-tab-node",
          type: "consoleLog",
          position: { x: 500, y: 300 },
          data: { label: "fromOtherTab", message: "hello" },
        },
      ],
      edges: [],
    },
  });
  expect(response.ok()).toBeTruthy();
  const payload = (await response.json()) as { updated_at: string };
  if (previousUpdatedAt) {
    expect(payload.updated_at).not.toBe(previousUpdatedAt);
  }
  return payload.updated_at;
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("clean tab: Run on a workflow changed elsewhere asks to reload", async ({ page }) => {
  const workflow = await createWorkflow(page, `Stale Clean ${Date.now()}`);
  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByTestId("node-palette-consoleLog").dblclick();
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    const localSavePromise = page.waitForResponse(
      (candidate) =>
        candidate.request().method() === "PUT" &&
        new URL(candidate.url()).pathname === `/api/workflows/${workflow.id}`,
    );
    await page.getByTestId("save-workflow-button").click();
    const localSave = await localSavePromise;
    await expect(page.getByTestId("save-workflow-button")).toBeDisabled();
    const localPayload = (await localSave.json()) as { updated_at: string };

    // Tab A is now clean and in sync. Another tab saves.
    await saveFromElsewhere(page, workflow.id, localPayload.updated_at);

    await page.getByRole("button", { name: "Run Workflow" }).click();

    await expect(page.getByText("Workflow Changed Elsewhere")).toBeVisible();
    await expect(page.getByRole("button", { name: "Reload and Run" })).toBeVisible();

    await page.getByRole("button", { name: "Reload and Run" }).click();
    // The canvas now shows the other tab's node, and the run proceeds.
    await expect(page.getByText("Last Executed Node")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("dirty tab: Run on a workflow changed elsewhere asks before overwriting", async ({ page }) => {
  const workflow = await createWorkflow(page, `Stale Dirty ${Date.now()}`);
  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByTestId("node-palette-consoleLog").dblclick();
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);

    // Unsaved local edits here, and another tab saves in the meantime.
    await saveFromElsewhere(page, workflow.id);

    await page.getByRole("button", { name: "Run Workflow" }).click();

    await expect(page.getByText("Stale Workflow Detected")).toBeVisible();
    await expect(page.getByRole("button", { name: "Override and Run" })).toBeVisible();

    await page.getByRole("button", { name: "Cancel Run" }).click();
    // Cancelling keeps the local edits and starts no run.
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await expect(page.getByTestId("save-workflow-button")).toBeEnabled();
    await expect(page.getByText("Last Executed Node")).toBeHidden();

    // Overriding saves this tab's version and runs it.
    await page.getByRole("button", { name: "Run Workflow" }).click();
    await page.getByRole("button", { name: "Override and Run" }).click();
    await expect(page.getByText("Last Executed Node")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("normal Save on a workflow changed elsewhere warns", async ({ page }) => {
  const workflow = await createWorkflow(page, `Stale Save ${Date.now()}`);
  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByTestId("node-palette-consoleLog").dblclick();
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);

    await saveFromElsewhere(page, workflow.id);

    await page.getByTestId("save-workflow-button").click();
    await expect(page.getByText("Stale Workflow Detected")).toBeVisible();
    await expect(page.getByRole("button", { name: "Override", exact: true })).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
