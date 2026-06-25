import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("fileUploadTrigger workflow returns a single-use upload curl on canvas run", async ({
  page,
}) => {
  const workflow = await createWorkflow(
    page,
    "File Upload Trigger E2E",
    [
      {
        id: "n1",
        type: "fileUploadTrigger",
        position: { x: 120, y: 120 },
        data: { label: "audio", ttlMinutes: 30, maxSizeMb: 50, allowedTypes: "audio/*" },
      },
    ],
    [],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);

    await page.getByRole("button", { name: "Run Workflow" }).click();

    // The debug panel surfaces the minted upload link instead of running the body.
    await expect(page.getByText("File upload required")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("pre", { hasText: "/api/file-intake/u/" })).toBeVisible();
    await expect(page.getByText("Max size: 50 MB")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("fileUploadTrigger node renders on the canvas with its label", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    "File Upload Trigger Config E2E",
    [
      {
        id: "n1",
        type: "fileUploadTrigger",
        position: { x: 120, y: 120 },
        data: { label: "audio", ttlMinutes: 60, maxSizeMb: 100, allowedTypes: "" },
      },
    ],
    [],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator(".vue-flow__node").first();
    await expect(node).toBeVisible({ timeout: 15_000 });
    await expect(node).toContainText("audio");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
