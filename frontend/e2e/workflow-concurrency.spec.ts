import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

const WAIT_NODES = [
  {
    id: "in",
    type: "textInput",
    position: { x: 80, y: 160 },
    data: { label: "start", value: "hi" },
  },
  {
    id: "wait",
    type: "wait",
    position: { x: 340, y: 160 },
    // Holds the slot until History has opened, even on a slow CI runner (seen at ~6 s).
    data: { label: "pause", duration: 15000 },
  },
  {
    id: "out",
    type: "output",
    position: { x: 600, y: 160 },
    data: { label: "done", message: "ok" },
  },
];
const WAIT_EDGES = [
  { id: "e1", source: "in", target: "wait" },
  { id: "e2", source: "wait", target: "out" },
];

test("the concurrency limit is set in Properties and survives a reload", async ({ page }) => {
  const workflow = await createWorkflow(page, `Concurrency Settings ${Date.now()}`);
  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    const settings = page.getByTestId("workflow-concurrency-settings");
    await expect(settings).toBeVisible();

    const toggled = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname === `/api/workflows/${workflow.id}`,
    );
    await settings.getByTestId("workflow-concurrency-toggle").click();
    await toggled;

    const limitInput = settings.getByTestId("workflow-concurrency-limit");
    await expect(limitInput).toHaveValue("1");
    const savedLimit = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname === `/api/workflows/${workflow.id}`,
    );
    await limitInput.fill("2");
    await limitInput.press("Tab");
    await savedLimit;

    await page.reload();
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await expect(page.getByTestId("workflow-concurrency-limit")).toHaveValue("2");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("a second production run waits in the queue and shows in History", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Concurrency Queue ${Date.now()}`,
    WAIT_NODES,
    WAIT_EDGES,
  );
  try {
    const update = await page.request.put(`/api/workflows/${workflow.id}`, {
      data: { concurrency_limit: 1 },
    });
    expect(update.ok()).toBeTruthy();

    const first = page.request.post(`/api/workflows/${workflow.id}/execute`, {
      data: { inputs: {} },
      timeout: 60_000,
    });
    await expect
      .poll(async () => {
        const active = await page.request.get("/api/workflows/executions/active");
        const items = (await active.json()) as { workflow_id: string }[];
        return items.filter((item) => item.workflow_id === workflow.id).length;
      })
      .toBe(1);

    const second = await page.request.post(`/api/workflows/${workflow.id}/execute`, {
      data: { inputs: {} },
    });
    expect(second.status()).toBe(202);
    const body = (await second.json()) as {
      execution_id: string;
      status_url: string;
      queue: { position: number; size: number; running: number; limit: number };
    };
    expect(body.queue).toEqual({ position: 1, size: 1, running: 1, limit: 1 });

    await page.goto(`/workflows/${workflow.id}`);
    await page.getByRole("button", { name: "History", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
    await expect(page.getByTestId(`active-execution-status-${body.execution_id}`)).toContainText(
      "Queued 1/1",
    );

    expect((await first).ok()).toBeTruthy();
    await expect
      .poll(
        async () => {
          const status = await page.request.get(new URL(body.status_url).pathname);
          return ((await status.json()) as { status: string }).status;
        },
        { timeout: 45_000 },
      )
      .toBe("success");

    // The run's status is final before its registry row is gone, and deletion waits for that.
    await expect
      .poll(async () => {
        const active = await page.request.get("/api/workflows/executions/active");
        const items = (await active.json()) as { workflow_id: string }[];
        return items.filter((item) => item.workflow_id === workflow.id).length;
      })
      .toBe(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
