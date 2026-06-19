import { expect, test } from "@playwright/test";

import {
  acceptNextDialog,
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

  const conversationId = page.url().split("/").pop();
  expect(conversationId).toBeTruthy();
  const activeConversation = page.getByTestId(`chat-list-item-${conversationId}`);
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
  const credentialResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/credentials",
  );
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const credentialResponse = await credentialResponsePromise;
  const credential = await credentialResponse.json() as { id: string };

  const credentialCard = page.getByTestId(`credential-card-${credential.id}`);
  await expect(credentialCard).toBeVisible();
  await acceptNextDialog(
    page,
    () => page.getByTestId(`credential-delete-${credential.id}`).click(),
    "Are you sure you want to delete this credential?",
  );
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
        data: { label: "cron", cronExpression: "0 12 * * 3" },
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

test("Global Variables supports create and delete", async ({ page }) => {
  const variableName = `e2eVariable${Date.now()}`;
  const variableValue = "playwright-value";

  await page.goto("/?tab=globalvariables");
  await expect(
    page.getByRole("heading", { name: "Global Variables", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /New Variable|Add Variable/ }).first().click();
  await page.getByLabel("Name").fill(variableName);
  await page.getByLabel("Value", { exact: true }).fill(variableValue);
  await page.getByRole("button", { name: "Create", exact: true }).click();

  const variableRow = page.getByTestId(`global-variable-${variableName}`);
  await expect(variableRow).toContainText(variableValue);
  await acceptNextDialog(
    page,
    () => variableRow.getByTitle("Delete").click(),
    "Are you sure you want to delete this variable?",
  );
  await expect(variableRow).toBeHidden();
});

test("Drive opens and shows the empty state", async ({ page }) => {
  await page.goto("/?tab=drive");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Drive", exact: true })).toBeVisible();
  await expect(main.getByText("No files yet", { exact: true })).toBeVisible();
});

test("Traces opens and shows the empty state", async ({ page }) => {
  await page.goto("/?tab=traces");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Traces", exact: true })).toBeVisible();
  await expect(main.getByText("No traces yet.", { exact: true })).toBeVisible();
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
  const templateCard = page.getByTestId(`template-card-${template.id}`);
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

  await acceptNextDialog(
    page,
    () => page.getByTitle("Delete suite").click(),
    "Are you sure you want to delete this eval suite? This cannot be undone.",
  );
  await expect(page.getByText("Create a suite to get started")).toBeVisible();
});
