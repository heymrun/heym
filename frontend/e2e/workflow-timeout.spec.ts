import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("a workflow timeout shorter than a wait node fails the run", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Timeout Wait ${Date.now()}`,
    [
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
        // 3s wait, but the workflow timeout below is only 1s.
        data: { label: "longWait", duration: 3000 },
      },
      {
        id: "out",
        type: "output",
        position: { x: 600, y: 160 },
        data: { label: "done", message: "$longWait" },
      },
    ],
    [
      { id: "e1", source: "in", target: "wait" },
      { id: "e2", source: "wait", target: "out" },
    ],
  );

  // Set a 1-second workflow timeout.
  const updateResponse = await page.request.put(`/api/workflows/${workflow.id}`, {
    data: { workflow_timeout_seconds: 1 },
  });
  expect(updateResponse.ok()).toBeTruthy();

  await page.goto(`/workflows/${workflow.id}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(3);

  const completionPromise = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === "POST" &&
      new URL(candidate.url()).pathname === `/api/workflows/${workflow.id}/execute/stream`,
    { timeout: 30_000 },
  );

  const started = Date.now();
  await page.getByRole("button", { name: "Run Workflow" }).click();

  const response = await completionPromise;
  const body = await response.text();
  const elapsedMs = Date.now() - started;

  // The run ended as an error because it exceeded the 1s timeout...
  expect(body).toMatch(/"status":\s*"error"/);
  expect(body.toLowerCase()).toContain("timed out");
  // ...and it stopped near the 1s deadline rather than after the full 3s wait.
  expect(elapsedMs).toBeLessThan(15_000);

  // The timeout error is also visible in the canvas execution log (not only history).
  await expect(page.getByText(/timed out/i)).toBeVisible();

  await deleteWorkflow(page, workflow.id);
});
