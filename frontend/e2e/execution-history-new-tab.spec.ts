import { expect, test, type Page } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

const HISTORY_NODES = [
  {
    id: "input_text",
    type: "textInput",
    position: { x: 80, y: 160 },
    data: { label: "userInput", value: "", inputFields: [{ key: "text" }] },
  },
  {
    id: "output_text",
    type: "output",
    position: { x: 340, y: 160 },
    data: { label: "finalOutput", message: "$userInput.body.text" },
  },
];
const HISTORY_EDGES = [{ id: "edge_input_output", source: "input_text", target: "output_text" }];

const CHAT_RUN_ID = "11111111-1111-4111-8111-111111111111";
const SECOND_CHAT_RUN_ID = "22222222-2222-4222-8222-222222222222";

async function runWorkflowOnce(page: Page, workflowId: string, text: string): Promise<string> {
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(2);
  await page.getByPlaceholder("Enter text...").fill(text);

  const completion = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === "POST" &&
      new URL(candidate.url()).pathname === `/api/workflows/${workflowId}/execute/stream`,
    { timeout: 30_000 },
  );
  await page.getByRole("button", { name: "Run Workflow" }).click();
  await completion;
  await expect(page.getByText("Last Executed Node")).toBeVisible();

  const history = await page.request.get(`/api/workflows/${workflowId}/history`);
  expect(history.ok()).toBeTruthy();
  const entryId = ((await history.json()) as { items: { id: string }[] }).items[0]?.id;
  expect(typeof entryId).toBe("string");
  return entryId as string;
}

async function expectPopupPath(popup: Page, path: string): Promise<void> {
  await popup.waitForLoadState("domcontentloaded");
  await expect.poll(() => new URL(popup.url()).pathname).toBe(path);
}

/** Two chat runs with distinct detail text; the first is selected when the list loads. */
async function mockChatOnlyHistory(page: Page): Promise<void> {
  const startedAt = new Date().toISOString();
  await page.route("**/api/workflows/history/all*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    await route.fulfill({
      json: {
        total: 2,
        items: [
          {
            id: CHAT_RUN_ID,
            workflow_id: null,
            workflow_name: "Dashboard chat",
            run_type: "dashboard_chat",
            started_at: startedAt,
            status: "success",
            execution_time_ms: 900,
          },
          {
            id: SECOND_CHAT_RUN_ID,
            workflow_id: null,
            workflow_name: "Dashboard chat",
            run_type: "dashboard_chat",
            started_at: startedAt,
            status: "success",
            execution_time_ms: 1200,
          },
        ],
      },
    });
  });

  const detail = (id: string, text: string) => ({
    id,
    workflow_id: null,
    workflow_name: "Dashboard chat",
    run_type: "dashboard_chat",
    inputs: {},
    outputs: { text },
    node_results: [],
    status: "success",
    execution_time_ms: 900,
    started_at: startedAt,
  });
  await page.route(`**/api/workflows/history/all/${CHAT_RUN_ID}`, async (route) => {
    await route.fulfill({ json: detail(CHAT_RUN_ID, "first chat reply") });
  });
  await page.route(`**/api/workflows/history/all/${SECOND_CHAT_RUN_ID}`, async (route) => {
    await route.fulfill({ json: detail(SECOND_CHAT_RUN_ID, "second chat reply") });
  });
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("ctrl+click opens a run from the editor history in a new tab", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `History New Tab ${Date.now()}`,
    HISTORY_NODES,
    HISTORY_EDGES,
  );

  try {
    const entryId = await runWorkflowOnce(page, workflow.id, "editor modifier payload");
    const editorPath = new URL(page.url()).pathname;

    await page.getByRole("button", { name: "History", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();

    const row = page.getByTestId(`execution-history-entry-${entryId}`);
    await expect(row).toHaveAttribute("title", /Ctrl\/Cmd\+click to open it in a new tab/);

    const [popup] = await Promise.all([
      page.waitForEvent("popup"),
      row.click({ modifiers: ["Control"] }),
    ]);
    await expectPopupPath(popup, `/workflows/${workflow.id}/${entryId}`);

    // The current tab keeps the dialog open and stays on the editor.
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe(editorPath);
    await popup.close();

    // A plain click still selects the run.
    await row.click();
    await expect(row).toHaveClass(/border-primary/);
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();

    // Ctrl+double-click is still one modified gesture: exactly one tab, and this tab stays put.
    const doubleClickPopups: Page[] = [];
    page.on("popup", (popup) => doubleClickPopups.push(popup));
    await row.dblclick({ modifiers: ["Control"] });
    await expect.poll(() => doubleClickPopups.length).toBeGreaterThanOrEqual(1);
    await expectPopupPath(doubleClickPopups[0], `/workflows/${workflow.id}/${entryId}`);
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe(editorPath);
    // Loading the first tab is the settle: the second click of the double-click must not add one.
    expect(doubleClickPopups).toHaveLength(1);
    await doubleClickPopups[0].close();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("ctrl+click opens a run from All History in a new tab", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `All History New Tab ${Date.now()}`,
    HISTORY_NODES,
    HISTORY_EDGES,
  );

  try {
    const entryId = await runWorkflowOnce(page, workflow.id, "all history modifier payload");

    await page.goto("/");
    await page.getByRole("button", { name: "History", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();

    const row = page.getByTestId(`all-execution-history-entry-${entryId}`);
    await expect(row).toBeVisible();
    await expect(row).toHaveAttribute("title", /Ctrl\/Cmd\+click to open it in a new tab/);

    const [popup] = await Promise.all([
      page.waitForEvent("popup"),
      row.click({ modifiers: ["Control"] }),
    ]);
    await expectPopupPath(popup, `/workflows/${workflow.id}/${entryId}`);

    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/");
    await popup.close();

    // A plain click still selects and reveals the run detail.
    await row.click();
    await expect(page.getByRole("button", { name: "Bring to Canvas" })).toBeVisible();

    // Ctrl+double-click: one tab, no navigation away from the dashboard.
    const doubleClickPopups: Page[] = [];
    page.on("popup", (popup) => doubleClickPopups.push(popup));
    await row.dblclick({ modifiers: ["Control"] });
    await expect.poll(() => doubleClickPopups.length).toBeGreaterThanOrEqual(1);
    await expectPopupPath(doubleClickPopups[0], `/workflows/${workflow.id}/${entryId}`);
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/");
    // Loading the first tab is the settle: the second click of the double-click must not add one.
    expect(doubleClickPopups).toHaveLength(1);
    await doubleClickPopups[0].close();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("ctrl+click on a chat run only selects it", async ({ page }) => {
  await mockChatOnlyHistory(page);
  await page.goto("/");
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();

  const chatRow = page.getByTestId(`all-execution-history-entry-${SECOND_CHAT_RUN_ID}`);
  await expect(chatRow).toBeVisible();
  await expect(chatRow).toHaveAttribute("title", "Click to select this run");

  let popups = 0;
  page.on("popup", () => {
    popups += 1;
  });
  await chatRow.click({ modifiers: ["Control"] });

  // The second chat run becomes the selected one; no tab is opened and the dialog stays.
  await expect(page.getByText("second chat reply")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
  expect(popups).toBe(0);
});
