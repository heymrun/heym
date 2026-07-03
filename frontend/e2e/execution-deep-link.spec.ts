import { expect, test, type Page } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

interface WorkflowNodeFixture {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

interface WorkflowEdgeFixture {
  id: string;
  source: string;
  target: string;
}

function workflowNode(
  id: string,
  type: string,
  x: number,
  y: number,
  data: Record<string, unknown>,
): WorkflowNodeFixture {
  return { id, type, position: { x, y }, data };
}

function workflowEdge(id: string, source: string, target: string): WorkflowEdgeFixture {
  return { id, source, target };
}

async function runWorkflowFromCanvas(
  page: Page,
  workflowId: string,
  nodeCount: number,
  inputs: Record<string, string>,
): Promise<void> {
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(nodeCount);

  for (const [key, value] of Object.entries(inputs)) {
    await page.getByPlaceholder(`Enter ${key}...`).fill(value);
  }

  const completionPromise = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === "POST" &&
      new URL(candidate.url()).pathname === `/api/workflows/${workflowId}/execute/stream`,
    { timeout: 30_000 },
  );
  await page.getByRole("button", { name: "Run Workflow" }).click();
  await completionPromise;
  await expect(page.getByText("Last Executed Node")).toBeVisible();
}

async function latestHistoryEntryId(page: Page, workflowId: string): Promise<string> {
  const response = await page.request.get(`/api/workflows/${workflowId}/history`);
  expect(response.ok()).toBeTruthy();
  const payload = (await response.json()) as { items: { id: string }[] };
  const entryId = payload.items[0]?.id;
  expect(typeof entryId).toBe("string");
  return entryId as string;
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("brings a past execution onto the canvas via /workflows/:id/:executionId", async ({
  page,
}) => {
  const workflow = await createWorkflow(
    page,
    `Deep Link Execution ${Date.now()}`,
    [
      workflowNode("input_text", "textInput", 80, 160, {
        label: "userInput",
        value: "",
        inputFields: [{ key: "text" }],
      }),
      workflowNode("output_text", "output", 340, 160, {
        label: "finalOutput",
        message: "$userInput.body.text",
      }),
    ],
    [workflowEdge("edge_input_output", "input_text", "output_text")],
  );

  try {
    await runWorkflowFromCanvas(page, workflow.id, 2, { text: "deeplink payload" });

    const entryId = await latestHistoryEntryId(page, workflow.id);

    // Fresh navigation to the deep link must reload the editor and bring the
    // referenced execution onto the canvas 1:1 with the dialog's "Bring to Canvas":
    // node/output mapping (Last Executed Node) AND the Execution Highlights popup.
    await page.goto(`/workflows/${workflow.id}/${entryId}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(2);
    await expect(page.getByText("Last Executed Node")).toBeVisible();
    await expect(page.getByTestId("execution-highlights-panel")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
