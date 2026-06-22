import { expect, test } from "@playwright/test";

import {
  createWorkflowTemplate,
  deleteWorkflow,
  deleteWorkflowTemplate,
  prepareAuthenticatedPage,
} from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("searches templates and creates a workflow from a template", async ({ page }) => {
  const templateName = `E2E Template ${Date.now()}`;
  const template = await createWorkflowTemplate(page, templateName);
  let createdWorkflowId: string | undefined;

  try {
    await page.goto("/?tab=templates");
    const templateCard = page.getByTestId(`template-card-${template.id}`);
    await expect(templateCard).toBeVisible();

    // Search narrows the grid to the matching template.
    const search = page.getByPlaceholder("Search templates…");
    await search.fill(templateName);
    await expect(templateCard).toBeVisible();

    // A non-matching query yields the empty state.
    await search.fill("definitely-not-a-real-template-name");
    await expect(page.getByText("No templates found")).toBeVisible();

    // Clearing the query brings the template back so it can be used.
    await search.fill("");
    await expect(templateCard).toBeVisible();
    await templateCard.getByRole("button", { name: "Use" }).click();
    await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]+$/);
    createdWorkflowId = page.url().split("/").pop();
  } finally {
    if (createdWorkflowId) {
      await deleteWorkflow(page, createdWorkflowId);
    }
    await deleteWorkflowTemplate(page, template.id);
  }
});

test("switches between Workflows and Nodes template kinds", async ({ page }) => {
  const templateName = `E2E Kind Template ${Date.now()}`;
  const template = await createWorkflowTemplate(page, templateName);

  try {
    await page.goto("/?tab=templates");
    await expect(page.getByTestId(`template-card-${template.id}`)).toBeVisible();
    await expect(page.getByPlaceholder("Search templates…")).toBeVisible();

    // The "Workflows" label also exists in the dashboard nav, so anchor the
    // kind toggle via its unique "Nodes" sibling.
    const nodesButton = page.getByRole("button", { name: "Nodes", exact: true });
    const kindToggle = nodesButton.locator("..");

    // Switching to the Nodes kind swaps the search placeholder and hides
    // workflow-kind templates.
    await nodesButton.click();
    await expect(page.getByPlaceholder("Search nodes…")).toBeVisible();
    await expect(page.getByTestId(`template-card-${template.id}`)).toHaveCount(0);

    // Switching back restores the workflow template grid.
    await kindToggle.getByRole("button", { name: "Workflows", exact: true }).click();
    await expect(page.getByTestId(`template-card-${template.id}`)).toBeVisible();
  } finally {
    await deleteWorkflowTemplate(page, template.id);
  }
});
