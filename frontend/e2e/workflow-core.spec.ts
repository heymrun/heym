import { expect, test } from "@playwright/test";

import {
  createWorkflow,
  deleteWorkflow,
  prepareAuthenticatedPage,
} from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("creates a folder and filters workflows with search", async ({ page }) => {
  const workflowName = `Searchable Workflow ${Date.now()}`;
  const folderName = `E2E Folder ${Date.now()}`;
  const workflow = await createWorkflow(page, workflowName);

  await page.goto("/");
  await page.getByRole("button", { name: "New Folder" }).first().click();
  await page.getByLabel("Folder Name").fill(folderName);
  await page.getByRole("button", { name: "Create", exact: true }).click();

  await expect(page.getByText(folderName, { exact: true })).toBeVisible();
  await page.getByPlaceholder("Search workflows").fill(workflowName);
  await expect(page.getByTestId(`workflow-card-${workflow.id}`)).toBeVisible();
  await page.getByPlaceholder("Search workflows").fill("definitely-not-present");
  await expect(page.getByText("No workflows found")).toBeVisible();

  await deleteWorkflow(page, workflow.id);
});

test("imports and exports a workflow JSON file", async ({ page }) => {
  const importedName = `Imported Workflow ${Date.now()}`;
  const importPayload = {
    name: importedName,
    nodes: [
      {
        id: "console-1",
        type: "consoleLog",
        position: { x: 120, y: 100 },
        data: { label: "consoleLog", logMessage: "$input" },
      },
    ],
    edges: [],
  };

  await page.goto("/");
  const dataTransfer = await page.evaluateHandle((payload) => {
    const transfer = new DataTransfer();
    transfer.items.add(
      new File([JSON.stringify(payload)], "imported-workflow.json", {
        type: "application/json",
      }),
    );
    return transfer;
  }, importPayload);
  await page.getByTestId("workflow-import-dropzone").dispatchEvent("drop", {
    dataTransfer,
  });

  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]+$/);
  await expect(page.getByTestId("workflow-title")).toHaveText(importedName);
  await expect(page.locator(".vue-flow__node")).toHaveCount(1);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.json$/);

  const workflowId = page.url().split("/").pop();
  if (workflowId) {
    await deleteWorkflow(page, workflowId);
  }
});

test("renders multiple connected nodes and persists the edge", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Connected Workflow ${Date.now()}`,
    [
      {
        id: "console-source",
        type: "consoleLog",
        position: { x: 100, y: 100 },
        data: { label: "consoleLog", logMessage: "$input" },
      },
      {
        id: "output-target",
        type: "output",
        position: { x: 500, y: 100 },
        data: { label: "output", output: "$input" },
      },
    ],
    [
      {
        id: "edge-console-output",
        source: "console-source",
        target: "output-target",
        sourceHandle: "output",
        targetHandle: "input",
      },
    ],
  );

  await page.goto(`/workflows/${workflow.id}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(2);
  await expect(page.locator(".vue-flow__edge-path")).toHaveCount(1);
  await page.reload();
  await expect(page.locator(".vue-flow__edge-path")).toHaveCount(1);

  await deleteWorkflow(page, workflow.id);
});

test("shows a failed workflow execution", async ({ page }) => {
  const workflow = await createWorkflow(page, `Failing Workflow ${Date.now()}`);

  await page.goto(`/workflows/${workflow.id}`);
  await page.getByTestId("node-palette-throwError").dblclick();
  await page.getByTestId("save-workflow-button").click();
  await page.getByRole("button", { name: "Run Workflow" }).click();

  await expect(page.getByText("Last Executed Node")).toBeVisible();
  await expect(page.getByText("error", { exact: true })).toBeVisible();
  await expect(page.getByText('"httpStatusCode": 400')).toBeVisible();

  await deleteWorkflow(page, workflow.id);
});
