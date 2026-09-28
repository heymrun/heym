import { expect, test, type Page, type Route } from "@playwright/test";

import { createWorkflow, deleteDataTable, deleteWorkflow, prepareAuthenticatedPage } from "./support";

/**
 * Data tables in the canvas AI Assistant. `/api/ai/workflow-assistant` is mocked; the
 * question card creates the table through the real backend, and the workflow the second
 * turn applies points at that table.
 */

const CREDENTIAL_ID = "00000000-0000-4000-8000-00000000e2e2";
const MODEL_ID = "gpt-e2e";
const QUESTION = "Which table should the leads go to?";
const CREATE_LABEL = "Create a new table";

function sse(text: string): string {
  return (
    `data: ${JSON.stringify({ type: "content", text })}\n\n` +
    `data: ${JSON.stringify({ type: "done" })}\n\n`
  );
}

function clarifyReply(tableName: string): string {
  const questions = [
    {
      id: "table",
      text: QUESTION,
      type: "single",
      allowOther: true,
      options: [
        {
          label: CREATE_LABEL,
          createTable: {
            name: tableName,
            description: "Leads from the form",
            columns: [
              { name: "email", type: "string", unique: true },
              { name: "name", type: "string" },
            ],
          },
        },
      ],
    },
  ];
  return [
    "I will store each lead in a data table.",
    "```heym-clarify",
    JSON.stringify({ questions }),
    "```",
  ].join("\n");
}

function workflowReply(tableId: string): string {
  const workflow = {
    nodes: [
      {
        id: "request",
        type: "textInput",
        position: { x: 0, y: 0 },
        data: { label: "request", inputFields: [{ key: "text" }] },
      },
      {
        id: "save-lead",
        type: "dataTable",
        position: { x: 300, y: 0 },
        data: {
          label: "saveLead",
          dataTableId: tableId,
          dataTableOperation: "insert",
          dataTableData: '{"email": "$request.text"}',
        },
      },
    ],
    edges: [{ id: "e1", source: "request", target: "save-lead" }],
  };
  return ["New leads now go to the table.", "```json", JSON.stringify(workflow), "```"].join("\n");
}

function createdTableId(message: string): string {
  return /Created data table ".+" \(id ([0-9a-f-]{36})\)/.exec(message)?.[1] ?? "";
}

async function mockAssistantCredentials(page: Page): Promise<void> {
  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({
      json: [
        {
          id: CREDENTIAL_ID,
          name: "E2E LLM",
          type: "openai",
          masked_value: null,
          header_key: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
  });
  await page.route(`**/api/credentials/${CREDENTIAL_ID}/models`, async (route) => {
    await route.fulfill({
      json: [{ id: MODEL_ID, name: MODEL_ID, is_reasoning: false, supports_batch: false }],
    });
  });
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await mockAssistantCredentials(page);
});

test("the question card creates a data table and the workflow uses it", async ({ page }) => {
  const tableName = `e2e_leads_${Date.now()}`;
  const messages: string[] = [];
  let tableId = "";
  await page.route("**/api/ai/workflow-assistant", async (route: Route) => {
    const body = route.request().postDataJSON() as { message?: string };
    const message = String(body.message ?? "");
    messages.push(message);
    tableId = tableId || createdTableId(message);
    const reply = messages.length === 1 ? clarifyReply(tableName) : workflowReply(tableId);
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body: sse(reply),
    });
  });
  const workflow = await createWorkflow(page, `Data Table Assistant ${Date.now()}`);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByTitle("AI Assistant").click();
    await expect(page.getByTestId("ai-assistant-title-toggle")).toBeVisible();
    const input = page.getByPlaceholder("What do you want to automate...");
    await expect(input).toBeEnabled();
    await input.fill("Save every lead from the form into a table");
    await input.press("Enter");

    await expect(page.getByText(QUESTION)).toBeVisible();
    await page.getByRole("button", { name: CREATE_LABEL }).click();
    const details = page.getByTestId("clarify-data-table-details");
    await expect(details).toContainText(`New table: ${tableName}`);
    await expect(details).toContainText("email · string · unique");
    await page.getByRole("button", { name: "Submit answers" }).click();

    await expect.poll(() => messages.length).toBe(2);
    expect(messages[1]).toContain(`Created data table "${tableName}"`);
    expect(tableId).toMatch(/^[0-9a-f-]{36}$/);
    const created = await page.request.get(`/api/data-tables/${tableId}`);
    expect(created.ok()).toBeTruthy();
    const body = (await created.json()) as { columns: { name: string }[] };
    expect(body.columns.map((column) => column.name)).toEqual(["email", "name"]);

    const saveNode = page.locator('.vue-flow__node[data-id="save-lead"]');
    await expect(saveNode).toBeVisible();
    // The floating assistant covers the properties panel; close it to inspect the node.
    await page.getByTitle("Close", { exact: true }).click();
    await expect(page.getByTestId("ai-assistant-title-toggle")).toBeHidden();
    // Selecting a node keeps the panel's current tab, and a workflow with an input opens on Run.
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await saveNode.click();
    const panel = page.locator(".properties-panel");
    await expect(panel.locator(`select:has(option[value="${tableId}"])`)).toHaveValue(tableId);
    await expect(panel.getByText("DataTable is required.")).toBeHidden();
  } finally {
    await deleteWorkflow(page, workflow.id);
    if (tableId) await deleteDataTable(page, tableId);
  }
});
