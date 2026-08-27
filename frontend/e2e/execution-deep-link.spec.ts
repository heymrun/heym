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

async function expectExecutionPath(
  page: Page,
  workflowId: string,
  entryId: string,
): Promise<void> {
  await expect
    .poll(() => new URL(page.url()).pathname)
    .toBe(`/workflows/${workflowId}/${entryId}`);
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

    await page.getByRole("button", { name: "History", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
    await page.getByRole("button", { name: "Bring to Canvas" }).click();
    await expectExecutionPath(page, workflow.id, entryId);

    await page.goto("/evals");
    await page.getByRole("button", { name: "History", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
    await page.keyboard.press("s");
    const allHistorySearch = page.getByPlaceholder(
      "Search by workflow name, trigger, status...",
    );
    const filteredHistoryResponse = page.waitForResponse(
      (candidate) => {
        const url = new URL(candidate.url());
        return (
          candidate.request().method() === "GET" &&
          url.pathname === "/api/workflows/history/all" &&
          url.searchParams.get("search") === workflow.name
        );
      },
      { timeout: 10_000 },
    );
    await allHistorySearch.fill(workflow.name);
    await filteredHistoryResponse;
    const matchingHistoryEntry = page.locator("button").filter({ hasText: workflow.name }).first();
    await expect(matchingHistoryEntry).toBeVisible();
    await matchingHistoryEntry.click();
    const bringToCanvasFromAllHistory = page
      .locator("div.space-y-3")
      .filter({ hasText: workflow.name })
      .getByRole("button", { name: "Bring to Canvas" });
    await expect(bringToCanvasFromAllHistory).toBeVisible();
    await bringToCanvasFromAllHistory.click();
    await expectExecutionPath(page, workflow.id, entryId);
    await expect(page.getByPlaceholder("Enter text...")).toHaveValue("deeplink payload");

    await page.locator('header a[href="/"]').first().click();
    await expect(page).toHaveURL(/\/$/);
    // The listing is a master/detail view: a click selects, a double-click opens the editor.
    await page.getByTestId(`workflow-card-${workflow.id}`).dblclick();
    await expect(page).toHaveURL(new RegExp(`/workflows/${workflow.id}$`));
    await expect(page.getByPlaceholder("Enter text...")).toHaveValue("");

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

test("opens one running execution live from both history dialogs", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Live Execution Canvas ${Date.now()}`,
    [
      workflowNode("input_live", "textInput", 80, 160, {
        label: "inputLive",
        inputFields: [{ key: "text" }],
      }),
      workflowNode("wait_live", "wait", 340, 160, {
        label: "waitLive",
        // Long enough for both history dialogs under CI (3 Playwright workers share the runner).
        duration: 18_000,
      }),
      workflowNode("set_live", "set", 600, 160, {
        label: "setLive",
        mappings: [{ key: "text", value: "$waitLive.text" }],
      }),
      workflowNode("wait_live_two", "wait", 860, 160, {
        label: "waitLiveTwo",
        duration: 3_000,
      }),
      workflowNode("output_live", "jsonOutputMapper", 1_120, 160, {
        label: "outputLive",
        mappings: [{ key: "message", value: "$waitLiveTwo.text" }],
      }),
    ],
    [
      workflowEdge("edge_input_wait", "input_live", "wait_live"),
      workflowEdge("edge_wait_set", "wait_live", "set_live"),
      workflowEdge("edge_set_wait_two", "set_live", "wait_live_two"),
      workflowEdge("edge_wait_two_output", "wait_live_two", "output_live"),
    ],
  );

  let executionId = "";
  const allHistoryPage = await page.context().newPage();
  try {
    // Warm the second page before the run starts so opening All History does not burn the
    // wait window (CI with parallel workers can make a cold dashboard load exceed 6s).
    await Promise.all([page.goto(`/workflows/${workflow.id}`), allHistoryPage.goto("/")]);
    await expect(page.locator(".vue-flow__node")).toHaveCount(5);
    await page.evaluate((workflowId) => {
      void fetch(`/api/workflows/${workflowId}/execute?trigger_source=E2E`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "x-simple-response": "false",
        },
        body: JSON.stringify({ text: "live input payload" }),
      });
    }, workflow.id);

    await expect
      .poll(async () => {
        const response = await page.request.get("/api/workflows/executions/active");
        const active = (await response.json()) as Array<{
          execution_id: string;
          workflow_id: string;
        }>;
        executionId =
          active.find((entry) => entry.workflow_id === workflow.id)?.execution_id ?? "";
        return executionId;
      })
      .not.toBe("");

    await page.getByRole("button", { name: "History", exact: true }).click();
    await page.getByTestId(`open-live-execution-${executionId}`).click();
    await expectExecutionPath(page, workflow.id, executionId);
    await expect(page.locator('[data-id="wait_live"] .node-base')).toHaveClass(
      /animate-heartbeat/,
    );
    await expect(page.getByPlaceholder("Enter text...")).toHaveValue("live input payload");
    await expect(page.getByTestId("debug-node-result-input_live")).toContainText("inputLive");

    await allHistoryPage.getByRole("button", { name: "History", exact: true }).click();
    await expect(
      allHistoryPage.getByRole("heading", { name: "Execution History" }),
    ).toBeVisible();
    await allHistoryPage.getByTestId(`open-live-execution-${executionId}`).click();
    await expectExecutionPath(allHistoryPage, workflow.id, executionId);
    await expect(allHistoryPage.locator('[data-id="wait_live"] .node-base')).toHaveClass(
      /animate-heartbeat/,
    );
    await expect(allHistoryPage.getByPlaceholder("Enter text...")).toHaveValue(
      "live input payload",
    );

    await expect(page.locator('[data-id="wait_live_two"] .node-base')).toHaveClass(
      /animate-heartbeat/,
      { timeout: 25_000 },
    );
    await expect(page.getByTestId("debug-node-result-wait_live_two")).toContainText(
      "waitLiveTwo",
    );

    await expect(page.getByTestId("execution-highlights-panel")).toBeVisible({
      timeout: 8_000,
    });
    await expect(allHistoryPage.getByTestId("execution-highlights-panel")).toBeVisible({
      timeout: 8_000,
    });
    await page.getByTitle("Execution timeline").click();
    await expect(page.getByTestId("execution-timeline-row-wait_live_two")).toContainText(
      "waitLiveTwo",
    );
    await page.getByTestId(/execution-timeline-span-wait_live_two-\d+$/).click();
    await expect(page.getByTestId("execution-span-details")).toContainText("waitLiveTwo");
  } finally {
    if (executionId) {
      await page.request.post(
        `/api/workflows/${workflow.id}/executions/${executionId}/cancel`,
      );
    }
    await allHistoryPage.close();
    await deleteWorkflow(page, workflow.id);
  }
});

test("keeps a canvas run live after dashboard navigation and history re-entry", async ({
  page,
}) => {
  const workflow = await createWorkflow(
    page,
    `Responsive Canvas Navigation ${Date.now()}`,
    [
      workflowNode("responsive_input", "textInput", 80, 160, {
        label: "start",
        inputFields: [{ key: "text" }],
      }),
      workflowNode("responsive_wait_a", "wait", 340, 160, {
        label: "wait",
        duration: 10_000,
      }),
      workflowNode("responsive_set", "set", 600, 160, {
        label: "set",
        mappings: [{ key: "text", value: "$wait.text" }],
      }),
      workflowNode("responsive_wait_b", "wait", 860, 160, {
        label: "wait1",
        duration: 2_000,
      }),
      workflowNode("responsive_output", "jsonOutputMapper", 1_120, 160, {
        label: "jsonResponse",
        mappings: [{ key: "message", value: "$wait1.text" }],
      }),
    ],
    [
      workflowEdge("edge_responsive_a", "responsive_input", "responsive_wait_a"),
      workflowEdge("edge_responsive_b", "responsive_wait_a", "responsive_set"),
      workflowEdge("edge_responsive_c", "responsive_set", "responsive_wait_b"),
      workflowEdge("edge_responsive_d", "responsive_wait_b", "responsive_output"),
    ],
  );

  let executionId = "";
  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(5);
    await page.getByRole("button", { name: "Run Workflow" }).click();

    await expect(page.locator('[data-id="responsive_wait_a"] .node-base')).toHaveClass(
      /animate-heartbeat/,
    );

    await expect
      .poll(async () => {
        const response = await page.request.get("/api/workflows/executions/active");
        const active = (await response.json()) as Array<{
          execution_id: string;
          workflow_id: string;
        }>;
        executionId =
          active.find((entry) => entry.workflow_id === workflow.id)?.execution_id ?? "";
        return executionId;
      })
      .not.toBe("");

    const navigationStartedAt = Date.now();
    await page.locator('header a[href="/"]').first().click();
    await expect(page).toHaveURL(/\/$/, { timeout: 4_000 });
    await expect(page.getByTestId(`workflow-card-${workflow.id}`)).toBeVisible({
      timeout: 4_000,
    });
    expect(Date.now() - navigationStartedAt).toBeLessThan(4_000);

    const healthResponse = await page.request.get("/api/health", {
      timeout: 2_000,
    });
    expect(healthResponse.ok()).toBeTruthy();

    await page.getByRole("button", { name: "History", exact: true }).click();
    await page.getByTestId(`open-live-execution-${executionId}`).click();
    await expectExecutionPath(page, workflow.id, executionId);
    await expect(page.locator('[data-id="responsive_wait_a"] .node-base')).toHaveClass(
      /animate-heartbeat/,
    );
    await expect(page.locator('[data-id="responsive_wait_b"] .node-base')).toHaveClass(
      /animate-heartbeat/,
      { timeout: 15_000 },
    );
    await expect(page.getByTestId("execution-highlights-panel")).toBeVisible({
      timeout: 8_000,
    });
  } finally {
    if (executionId) {
      await page.request.post(
        `/api/workflows/${workflow.id}/executions/${executionId}/cancel`,
      );
    }
    await deleteWorkflow(page, workflow.id);
  }
});
