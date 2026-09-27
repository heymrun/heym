import { expect, test, type Page, type Route } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

/**
 * YOLO mode in the canvas AI Assistant. `/api/ai/workflow-assistant` is mocked with
 * canned turns; the workflow it builds really runs on the canvas.
 */

const CREDENTIAL_ID = "00000000-0000-4000-8000-00000000e2e1";
const MODEL_ID = "gpt-e2e";
const PROMPT = "Build a workflow that echoes the text back";

const ECHO_WORKFLOW = {
  nodes: [
    {
      id: "request",
      type: "textInput",
      position: { x: 0, y: 0 },
      data: { label: "request", inputFields: [{ key: "text" }] },
    },
    {
      id: "echo",
      type: "output",
      position: { x: 300, y: 0 },
      data: { label: "echo", message: "$request.text" },
    },
  ],
  edges: [{ id: "e1", source: "request", target: "echo" }],
};

const BUILD_REPLY = [
  "Here is an echo workflow.",
  "```json",
  JSON.stringify(ECHO_WORKFLOW),
  "```",
  "```heym-yolo",
  JSON.stringify({
    action: "run",
    inputs: { text: "hello from yolo" },
    expect: "The echo node returns the text",
  }),
  "```",
].join("\n");

const DONE_REPLY = [
  "The run returned the text unchanged.",
  "```heym-yolo",
  JSON.stringify({ action: "done", summary: "Attempt 1 echoed the input." }),
  "```",
].join("\n");

function sse(text: string): string {
  return (
    `data: ${JSON.stringify({ type: "content", text })}\n\n` +
    `data: ${JSON.stringify({ type: "done" })}\n\n`
  );
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

async function mockAssistantTurns(
  page: Page,
  replies: string[],
): Promise<Record<string, unknown>[]> {
  const requests: Record<string, unknown>[] = [];
  await page.route("**/api/ai/workflow-assistant", async (route: Route) => {
    requests.push(route.request().postDataJSON() as Record<string, unknown>);
    const reply = replies[Math.min(requests.length - 1, replies.length - 1)];
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body: sse(reply),
    });
  });
  return requests;
}

async function openAssistant(page: Page, workflowId: string): Promise<void> {
  await page.goto(`/workflows/${workflowId}`);
  await page.getByTitle("AI Assistant").click();
  await expect(page.getByTestId("ai-assistant-title-toggle")).toBeVisible();
  await expect(page.getByPlaceholder("What do you want to automate...")).toBeEnabled();
}

async function sendPrompt(page: Page): Promise<void> {
  const input = page.getByPlaceholder("What do you want to automate...");
  await input.fill(PROMPT);
  await input.press("Enter");
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await mockAssistantCredentials(page);
});

test("YOLO mode builds, runs and verifies a workflow on the canvas", async ({ page }) => {
  const requests = await mockAssistantTurns(page, [BUILD_REPLY, DONE_REPLY]);
  const workflow = await createWorkflow(page, `YOLO Echo ${Date.now()}`);

  try {
    await openAssistant(page, workflow.id);
    const checkbox = page.getByTestId("ai-assistant-yolo-checkbox");
    await expect(checkbox).not.toBeChecked();
    const yoloInfo = page.getByTestId("ai-assistant-yolo-info");
    await expect(yoloInfo).toBeVisible();
    await yoloInfo.hover();
    await expect(page.getByRole("tooltip")).toContainText("Runs the workflow after each change");

    // Scoped to the panel's mode toggle: the node palette also has an "Agent" button.
    const modeToggle = page.locator(".mode-toggle");
    await modeToggle.getByRole("button", { name: "Ask", exact: true }).click();
    await expect(checkbox).toBeHidden();
    await modeToggle.getByRole("button", { name: "Agent", exact: true }).click();

    await checkbox.check();
    await sendPrompt(page);

    await expect(page.getByTestId("ai-assistant-yolo-inputs")).toBeVisible();
    await expect(page.getByTestId("ai-assistant-yolo-input-text")).toHaveValue("hello from yolo");
    await page.getByTestId("ai-assistant-yolo-inputs-run").click();

    const steps = page.getByTestId("ai-assistant-yolo-steps").first();
    await expect(steps.getByText("Running workflow · attempt 1/5")).toBeVisible({
      timeout: 60_000,
    });
    await expect(steps.getByText("Executing echo")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("ai-assistant-yolo-report")).toContainText(
      "Attempt 1 result sent · success",
    );
    await expect(page.getByText("Verified in 1 attempt")).toBeVisible({ timeout: 60_000 });

    expect(requests).toHaveLength(2);
    expect(requests[0].yolo_mode).toBe(true);
    expect(requests[1].yolo_mode).toBe(true);
    expect(String(requests[1].message)).toContain("[YOLO run report] Attempt 1 of 5");
    const executionLog = requests[1].execution_log as { node_results?: unknown[] } | null;
    expect(executionLog?.node_results?.length ?? 0).toBeGreaterThan(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("Stop on the test inputs card ends the YOLO loop without a run", async ({ page }) => {
  const requests = await mockAssistantTurns(page, [BUILD_REPLY]);
  const workflow = await createWorkflow(page, `YOLO Stop ${Date.now()}`);

  try {
    await openAssistant(page, workflow.id);
    await page.getByTestId("ai-assistant-yolo-checkbox").check();
    await sendPrompt(page);

    await expect(page.getByTestId("ai-assistant-yolo-inputs")).toBeVisible();
    await page.getByTestId("ai-assistant-yolo-inputs-stop").click();

    const steps = page.getByTestId("ai-assistant-yolo-steps");
    await expect(steps.getByText("Stopped", { exact: true })).toBeVisible();
    await expect(page.getByTestId("ai-assistant-yolo-inputs-run")).toBeHidden();
    await expect(page.getByPlaceholder("What do you want to automate...")).toBeEnabled();
    expect(requests).toHaveLength(1);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
