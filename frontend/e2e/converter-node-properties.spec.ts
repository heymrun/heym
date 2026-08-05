import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows Converter csvToJson fields", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Converter CSV Properties ${Date.now()}`,
    [
      {
        id: "converter-node",
        type: "converter",
        position: { x: 120, y: 160 },
        data: {
          label: "converter",
          conversion: "csvToJson",
          source: "$input.text",
          delimiter: ",",
          hasHeader: true,
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="converter-node"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("converter-conversion-field")).toBeVisible();
    await expect(panel.getByTestId("converter-source-field")).toBeVisible();
    await expect(panel.getByTestId("converter-delimiter-field")).toBeVisible();
    await expect(panel.getByTestId("converter-has-header-field")).toBeVisible();
    await expect(panel.getByTestId("converter-trim-values-field")).toBeVisible();
    // jsonToCsv-only fields are hidden for the csvToJson direction.
    await expect(panel.getByTestId("converter-include-header-field")).toHaveCount(0);
    await expect(panel.getByTestId("converter-columns-field")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("shows Converter jsonToCsv fields", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Converter JSON Properties ${Date.now()}`,
    [
      {
        id: "converter-node",
        type: "converter",
        position: { x: 120, y: 160 },
        data: {
          label: "converter",
          conversion: "jsonToCsv",
          source: "$input",
          delimiter: ",",
          includeHeader: true,
          converterColumns: "name, age",
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="converter-node"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("converter-conversion-field")).toBeVisible();
    await expect(panel.getByTestId("converter-source-field")).toBeVisible();
    await expect(panel.getByTestId("converter-include-header-field")).toBeVisible();
    await expect(panel.getByTestId("converter-columns-field")).toBeVisible();
    // csvToJson-only toggles are hidden for the jsonToCsv direction.
    await expect(panel.getByTestId("converter-has-header-field")).toHaveCount(0);
    await expect(panel.getByTestId("converter-trim-values-field")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
