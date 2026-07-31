import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("Cal.com Trigger renders its signed webhook configuration", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Cal.com Trigger ${Date.now()}`,
    [
      {
        id: "cal-trigger",
        type: "calTrigger",
        position: { x: 120, y: 160 },
        data: {
          label: "calEvent",
          credentialId: "",
        },
      },
    ],
    [],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator('.vue-flow__node[data-id="cal-trigger"]');
    await expect(node).toBeVisible({ timeout: 15_000 });
    await expect(node).toContainText("calEvent");

    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await node.click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByText("Webhook Secret Credential")).toBeVisible();
    await expect(panel.getByText("No credential set — Cal.com requests will be rejected")).toBeVisible();
    await expect(panel.getByText("Available output fields")).toBeVisible();
    await expect(panel.locator('input[readonly]')).toHaveValue(
      /\/api\/cal\/webhook\/cal-trigger$/,
    );
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
