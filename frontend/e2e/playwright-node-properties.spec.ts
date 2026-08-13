import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows Playwright Mode dropdown with Run Code", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Playwright Mode ${Date.now()}`,
    [
      {
        id: "pw-node",
        type: "playwright",
        position: { x: 120, y: 160 },
        data: {
          label: "playwright",
          playwrightMode: "steps",
          playwrightSteps: [],
          playwrightCode: "",
          playwrightHeadless: true,
          playwrightTimeout: 30000,
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="pw-node"]').click();

    const panel = page.locator(".properties-panel");
    const modeField = panel.getByTestId("playwright-mode-field");
    await expect(modeField).toBeVisible();
    await expect(modeField.locator("select")).toHaveValue("steps");
    await expect(modeField.locator("option[value='code']")).toHaveText("Run Code");

    const stealthField = panel.getByTestId("playwright-stealth-field");
    await expect(stealthField).toBeVisible();
    await expect(stealthField.getByText("Reduce automation flags")).toBeVisible();
    await expect(stealthField.locator("#playwright-stealth")).not.toBeChecked();

    await modeField.locator("select").selectOption("code");
    await expect(panel.getByTestId("playwright-code-field")).toBeVisible();
    await expect(panel.getByText("Auth & Session")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("uses a searchable model dropdown for Playwright AI step", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Playwright AI Step ${Date.now()}`,
    [
      {
        id: "pw-node",
        type: "playwright",
        position: { x: 120, y: 160 },
        data: {
          label: "playwright",
          playwrightMode: "steps",
          playwrightSteps: [
            {
              action: "aiStep",
              instructions: "Click the login button",
              credentialId: "",
              model: "",
            },
          ],
          playwrightCode: "",
          playwrightHeadless: true,
          playwrightTimeout: 30000,
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="pw-node"]').click();

    const modelField = page.locator(".properties-panel").getByTestId("playwright-ai-step-model-field");
    await expect(modelField).toBeVisible();
    await expect(modelField.getByRole("combobox")).toBeVisible();
    await expect(modelField.locator("select")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
