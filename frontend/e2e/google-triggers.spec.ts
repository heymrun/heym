import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("Google Drive Trigger switches between folder and file scope", async ({ page }) => {
  const workflow = await createWorkflow(page, `Drive Trigger ${Date.now()}`, [
    {
      id: "drive-trigger",
      type: "googleDriveTrigger",
      position: { x: 120, y: 160 },
      data: {
        label: "contractsFolder",
        credentialId: "",
        gdtScope: "folder",
        gdtFolderId: "",
        gdtFileId: "",
        gdtEvents: ["created", "updated", "deleted"],
        gdtIncludeFolders: false,
        pollIntervalMinutes: 1,
      },
    },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="drive-trigger"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("gdt-credential-field")).toBeVisible();
    await expect(panel.getByTestId("gdt-folder-field")).toBeVisible();
    await expect(panel.getByTestId("gdt-events-field").getByLabel("File created")).toBeChecked();
    await expect(panel.getByTestId("gdt-output-fields")).toContainText("$contractsFolder.file.id");

    await panel.getByTestId("gdt-scope-field").locator("select").selectOption("file");
    await expect(panel.getByTestId("gdt-file-field")).toBeVisible();
    await expect(panel.getByTestId("gdt-folder-field")).toHaveCount(0);
    await expect(panel.getByTestId("gdt-events-field").getByLabel("File created")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("Google Sheets Trigger shows key column, write-back warning and outputs", async ({ page }) => {
  const workflow = await createWorkflow(page, `Sheets Trigger ${Date.now()}`, [
    {
      id: "sheet-trigger",
      type: "googleSheetsTrigger",
      position: { x: 120, y: 160 },
      data: {
        label: "newLead",
        credentialId: "",
        gstSpreadsheetId: "",
        gstSheetName: "Leads",
        gstHasHeader: true,
        gstKeyColumn: "",
        gstEvents: ["created"],
        pollIntervalMinutes: 1,
      },
    },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="sheet-trigger"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("gst-spreadsheet-field")).toBeVisible();
    await expect(panel.getByTestId("gst-key-column-field")).toBeVisible();
    await expect(panel.getByTestId("gst-write-back-warning")).toBeVisible();
    const events = panel.getByTestId("gst-events-field");
    await expect(events.getByLabel("Row added")).toBeChecked();
    await expect(events.getByLabel("Row updated")).not.toBeChecked();
    await expect(panel.getByTestId("gst-output-fields")).toContainText("$newLead.row.rowIndex");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
