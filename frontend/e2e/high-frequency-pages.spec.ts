import { expect, test } from "@playwright/test";

import {
  createWorkflow,
  deleteWorkflow,
  expectOk,
  prepareAuthenticatedPage,
} from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("Chats opens and supports conversation create/delete", async ({ page }) => {
  await page.goto("/chats");
  await expect(page.getByText("Ask to run a workflow")).toBeVisible();
  await page.getByRole("button", { name: "New Chat", exact: true }).click();
  await expect(page).toHaveURL(/\/chats\/[0-9a-f-]+$/);

  const activeConversation = page.locator(".group").filter({ hasText: "New Chat" }).first();
  await expect(activeConversation).toBeVisible();
  await activeConversation.hover();
  await activeConversation.getByTitle("Delete").click();
  await activeConversation.getByTitle("Confirm delete").click();
  await expect(page).toHaveURL(/\/chats$/);
});

test("Credentials opens and supports credential create/delete", async ({ page }) => {
  const credentialName = `e2e-bearer-${Date.now()}`;

  await page.goto("/?tab=credentials");
  await expect(
    page.getByRole("main").getByRole("heading", { name: "Credentials", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /New Credential|Add Credential/ }).first().click();
  await page.getByLabel("Name").fill(credentialName);
  await page.locator("#cred-type select").selectOption("bearer");
  await page.getByLabel("Bearer Token").fill("e2e-secret-token");
  await page.getByRole("button", { name: "Create", exact: true }).click();

  const credentialCard = page.locator(".credential-card").filter({ hasText: credentialName });
  await expect(credentialCard).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await credentialCard.getByTitle("Delete credential").click();
  await expect(credentialCard).toBeHidden();
});

test("Scheduled opens and reflects cron workflow lifecycle", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Scheduled Workflow ${Date.now()}`,
    [
      {
        id: "cron-1",
        type: "cron",
        position: { x: 100, y: 100 },
        data: { label: "cron", cronExpression: "* * * * *" },
      },
    ],
  );

  await page.goto("/?tab=schedules");
  await expect(page.getByRole("button", { name: "This Week" })).toBeVisible();
  await expect(page.getByText(workflow.name).first()).toBeVisible();

  await deleteWorkflow(page, workflow.id);
  await page.reload();
  await expect(page.getByText(workflow.name)).toHaveCount(0);
});

test("Templates opens and creates a workflow from a template", async ({ page }) => {
  const templateName = `E2E Template ${Date.now()}`;
  const templateResponse = await page.request.post("/api/templates", {
    data: {
      kind: "workflow",
      workflow: {
        name: templateName,
        description: "Playwright template",
        tags: ["e2e"],
        nodes: [],
        edges: [],
        visibility: "everyone",
      },
    },
  });
  await expectOk(templateResponse);
  const template = await templateResponse.json() as { id: string };

  await page.goto("/?tab=templates");
  const templateCard = page.locator(".group").filter({ hasText: templateName }).first();
  await expect(templateCard).toBeVisible();
  await templateCard.getByRole("button", { name: "Use" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]+$/);

  const createdWorkflowId = page.url().split("/").pop();
  if (createdWorkflowId) {
    await deleteWorkflow(page, createdWorkflowId);
  }
  await expectOk(await page.request.delete(`/api/templates/workflow/${template.id}`));
});

test("Evals opens and supports suite create/delete", async ({ page }) => {
  await page.goto("/evals");
  await expect(page.getByText("Create a suite to get started")).toBeVisible();
  await page.getByRole("button", { name: "Create your first suite" }).click();
  await expect(page.getByTestId("eval-suite-name")).toHaveValue("New Eval Suite");

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTitle("Delete suite").click();
  await expect(page.getByText("Create a suite to get started")).toBeVisible();
});
