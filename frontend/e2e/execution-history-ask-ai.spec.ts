import { expect, test, type Page } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

const CREDENTIAL_ID = "22222222-2222-4222-8222-22222222222a";

function inputOutputNodes(): Record<string, unknown>[] {
  return [
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
}

const INPUT_OUTPUT_EDGES = [{ id: "edge_input_output", source: "input_text", target: "output_text" }];

async function runOnce(page: Page, workflowId: string): Promise<string> {
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(2);
  await page.getByPlaceholder("Enter text...").fill("ask ai payload");

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

async function runOnceAndOpenHistory(page: Page, workflowId: string): Promise<string> {
  const entryId = await runOnce(page, workflowId);
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
  await expect(page.getByTestId(`execution-history-entry-${entryId}`)).toBeVisible();
  return entryId;
}

async function openDashboardHistory(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
}

/** A model to send with, a send endpoint that records the body, and a stream that stays open. */
async function mockChatSend(page: Page, sentBodies: string[]): Promise<void> {
  const now = new Date().toISOString();
  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({
      json: [
        {
          id: CREDENTIAL_ID,
          name: "Mock OpenAI",
          type: "openai",
          masked_value: "sk-...",
          header_key: null,
          created_at: now,
        },
      ],
    });
  });
  await page.route(`**/api/credentials/${CREDENTIAL_ID}/models`, async (route) => {
    await route.fulfill({
      json: [
        {
          id: "gpt-4o",
          name: "GPT-4o",
          is_reasoning: false,
          supports_batch: false,
          batch_support_reason: null,
          context_window: 128000,
        },
      ],
    });
  });
  await page.route("**/api/chats/*/context-summary**", async (route) => {
    await route.fulfill({
      json: {
        used: 0,
        limit: 128000,
        breakdown: { system: 0, agents_md: 0, workflows: 0, user_rules: 0, history: 0, attachment: 0 },
      },
    });
  });
  await page.route("**/api/chats/*/messages", async (route) => {
    const body = route.request().postDataJSON() as { content: string };
    sentBodies.push(body.content);
    const conversationId = new URL(route.request().url()).pathname.split("/")[3];
    await route.fulfill({
      status: 202,
      json: {
        conversation_id: conversationId,
        status: "started",
        user_message: {
          id: "55555555-5555-4555-8555-555555555555",
          role: "user",
          content: body.content,
          created_at: now,
        },
        queued_message: null,
      },
    });
  });
  // Never answered: the reply is not under test, and an open stream keeps the sent message on screen.
  await page.route("**/api/chats/*/stream", () => undefined);
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("Ask AI opens Chat with the workflow and run as removable context", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Ask AI History ${Date.now()}`,
    inputOutputNodes(),
    INPUT_OUTPUT_EDGES,
  );
  let conversationId: string | undefined;

  try {
    const entryId = await runOnceAndOpenHistory(page, workflow.id);
    const sentBodies: string[] = [];
    await mockChatSend(page, sentBodies);

    await page.getByTestId("execution-history-ask-ai").click();
    // Lands on /chats/<id> once the new conversation is created on the server.
    await expect(page).toHaveURL(/\/chats\/[0-9a-f-]+$/, { timeout: 20_000 });
    conversationId = page.url().split("/").pop();

    const composer = page.locator(".chat-input-area");
    await expect(composer.getByTestId("chat-context-chip-workflow")).toContainText(
      `Workflow: ${workflow.name}`,
    );
    await expect(composer.getByTestId("chat-context-chip-execution")).toContainText(
      `Execution: ${entryId.slice(0, 8)}…`,
    );

    await composer.getByRole("button", { name: "Remove workflow context" }).click();
    await expect(composer.getByTestId("chat-context-chip-workflow")).toHaveCount(0);
    await expect(composer.getByTestId("chat-context-chip-execution")).toBeVisible();

    const messageBox = page.getByPlaceholder("Type a message...");
    await expect(messageBox).toBeEnabled();
    await messageBox.fill("What did this run do?");
    await page.getByRole("button", { name: "Send message" }).click();

    await expect.poll(() => sentBodies.length).toBe(1);
    expect(sentBodies[0]).toBe(
      `What did this run do?\n\n[HEYM CONTEXT]\n- Execution: ${entryId} (workflow_id: ${workflow.id})`,
    );

    // The composer is cleared, and the sent bubble shows the question with the chip, not the block.
    await expect(composer.getByTestId("chat-context-chips")).toHaveCount(0);
    const bubble = page.locator(".chat-markdown").filter({ hasText: "What did this run do?" });
    await expect(bubble).toBeVisible();
    await expect(page.getByText("[HEYM CONTEXT]")).toHaveCount(0);
    await expect(
      page.getByTestId("chat-context-chip-execution").filter({ hasText: entryId.slice(0, 8) }),
    ).toBeVisible();
  } finally {
    if (conversationId) {
      await page.request.delete(`/api/chats/${conversationId}`);
    }
    await deleteWorkflow(page, workflow.id);
  }
});

test("history dialog switches the run detail between logs and the span timeline", async ({
  page,
}) => {
  const workflow = await createWorkflow(
    page,
    `History Timeline ${Date.now()}`,
    inputOutputNodes(),
    INPUT_OUTPUT_EDGES,
  );

  try {
    await runOnceAndOpenHistory(page, workflow.id);
    await expect(page.getByRole("button", { name: "Expand All" })).toBeVisible();

    const viewToggle = page.getByTestId("execution-history-timeline-toggle");
    await expect(viewToggle).toHaveText("Timeline");
    await viewToggle.click();
    const timeline = page.getByTestId("execution-history-timeline");
    await expect(timeline).toBeVisible();
    await expect(viewToggle).toHaveText("Logs");
    await expect(timeline.getByTestId("execution-timeline-row-input_text")).toBeVisible();
    await expect(timeline.getByTestId("execution-timeline-row-output_text")).toBeVisible();
    await expect(page.getByRole("button", { name: "Expand All" })).toHaveCount(0);

    await viewToggle.click();
    await expect(timeline).toHaveCount(0);
    await expect(viewToggle).toHaveText("Timeline");
    await expect(page.getByRole("button", { name: "Expand All" })).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("dashboard history offers Ask AI and the timeline for a workflow run", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `All History Ask AI ${Date.now()}`,
    inputOutputNodes(),
    INPUT_OUTPUT_EDGES,
  );
  let conversationId: string | undefined;

  try {
    const entryId = await runOnce(page, workflow.id);
    await openDashboardHistory(page);
    await page.getByTestId(`all-execution-history-entry-${entryId}`).click();
    await expect(page.getByText("Assistant response")).toHaveCount(0);

    await page.getByTestId("execution-history-timeline-toggle").click();
    const timeline = page.getByTestId("execution-history-timeline");
    await expect(timeline.getByTestId("execution-timeline-row-input_text")).toBeVisible();
    await expect(timeline.getByTestId("execution-timeline-row-output_text")).toBeVisible();
    await expect(page.getByRole("button", { name: "Expand All" })).toHaveCount(0);

    await page.getByTestId("execution-history-ask-ai").click();
    // Lands on /chats/<id> once the new conversation is created on the server.
    await expect(page).toHaveURL(/\/chats\/[0-9a-f-]+$/, { timeout: 20_000 });
    conversationId = page.url().split("/").pop();

    const composer = page.locator(".chat-input-area");
    await expect(composer.getByTestId("chat-context-chip-workflow")).toContainText(
      `Workflow: ${workflow.name}`,
    );
    await expect(composer.getByTestId("chat-context-chip-execution")).toContainText(
      `Execution: ${entryId.slice(0, 8)}…`,
    );
  } finally {
    if (conversationId) {
      await page.request.delete(`/api/chats/${conversationId}`);
    }
    await deleteWorkflow(page, workflow.id);
  }
});

test("dashboard history hides Ask AI and the timeline for a chat run", async ({ page }) => {
  const entryId = "66666666-6666-4666-8666-666666666666";
  const startedAt = new Date().toISOString();
  const chatRun = {
    id: entryId,
    workflow_id: null,
    workflow_name: "Dashboard Chat",
    run_type: "dashboard_chat",
    started_at: startedAt,
    status: "success",
    execution_time_ms: 1200,
    trigger_source: "DASHBOARD_CHAT",
  };
  await page.route("**/api/workflows/history/all**", async (route) => {
    const { pathname } = new URL(route.request().url());
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    if (pathname.endsWith(`/history/all/${entryId}`)) {
      await route.fulfill({
        json: {
          ...chatRun,
          inputs: { message: "hello" },
          outputs: { text: "Hi there" },
          node_results: [],
        },
      });
      return;
    }
    await route.fulfill({ json: { total: 1, items: [chatRun] } });
  });

  await openDashboardHistory(page);
  await page.getByTestId(`all-execution-history-entry-${entryId}`).click();
  await expect(page.getByText("Assistant response")).toBeVisible();
  await expect(page.getByTestId("execution-history-ask-ai")).toHaveCount(0);
  await expect(page.getByTestId("execution-history-timeline-toggle")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Expand All" })).toBeVisible();
});
