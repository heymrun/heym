import { expect, test } from "@playwright/test";

import { mockVersionCheck } from "./support";

test.beforeEach(async ({ page }) => {
  await mockVersionCheck(page);
});

test("creates, edits, saves, runs, reloads, and deletes a workflow", async ({ page }) => {
  const workflowName = `E2E Workflow ${Date.now()}`;
  const renamedWorkflow = `${workflowName} Renamed`;

  await page.addInitScript(() => {
    window.localStorage.setItem("showcase_seen_dashboard_workflows", "1");
    window.localStorage.setItem("showcase_seen_editor", "1");
  });
  await page.goto("/");
  await expect(
    page.getByRole("main").getByRole("heading", { name: "Workflows" }),
  ).toBeVisible();

  await page.getByTestId("new-workflow-button").click();
  await expect(page.getByRole("heading", { name: "Create New Workflow" })).toBeVisible();
  const createForm = page.locator("form").filter({
    has: page.getByLabel("Description (optional)"),
  });
  await createForm.getByLabel("Name", { exact: true }).fill(workflowName);
  await createForm.getByLabel("Description (optional)").fill("Created by Playwright");
  await createForm.getByRole("button", { name: "Create Workflow" }).click();

  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]+$/);
  await expect(page.getByTestId("workflow-title")).toHaveText(workflowName);

  await page.getByTestId("workflow-title").dispatchEvent("mousedown");
  const titleInput = page.locator("[data-heym-inline-edit] input").first();
  await titleInput.fill(renamedWorkflow);
  await titleInput.press("Enter");
  await expect(page.getByTestId("workflow-title")).toHaveText(renamedWorkflow);

  await page.getByTestId("node-palette-consoleLog").dblclick();
  await expect(page.locator(".vue-flow__node")).toHaveCount(1);

  const saveButton = page.getByTestId("save-workflow-button");
  await expect(saveButton).toBeEnabled();
  await saveButton.click();
  await expect(saveButton).toBeDisabled();

  await page.getByRole("button", { name: "Run Workflow" }).click();
  await expect(page.getByText("Last Executed Node")).toBeVisible();
  await expect(page.getByText("success", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("workflow-title")).toHaveText(renamedWorkflow);
  await expect(page.locator(".vue-flow__node")).toHaveCount(1);

  await page.getByRole("link", { name: "Heym" }).first().click();
  await expect(page).toHaveURL("/");

  const workflowCard = page.locator(".workflow-card").filter({ hasText: renamedWorkflow });
  await expect(workflowCard).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await workflowCard.getByTitle("Delete workflow").click();
  await expect(workflowCard).toBeHidden();
  await expect(page.getByText("Workflow deleted successfully")).toBeVisible();
});
