import { expect, test, type Page } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

interface RunResult {
  status: string;
  node_results: Array<{ node_id: string; output: Record<string, unknown> }>;
}

async function completion(page: Page, workflowId: string): Promise<RunResult> {
  const response = await page.waitForResponse((candidate) =>
    candidate.request().method() === "POST"
    && new URL(candidate.url()).pathname === `/api/workflows/${workflowId}/execute/stream`);
  expect(response.ok()).toBe(true);
  expect(new URL(response.url()).searchParams.get("run_until_node_id")).toBe("target");
  const body = await response.text();
  const events = body.split("\n").filter((line) => line.startsWith("data: "))
    .map((line) => JSON.parse(line.slice(6)) as RunResult & { type: string });
  const result = events.find((event) => event.type === "execution_complete");
  expect(result).toBeDefined();
  return result!;
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

for (const inputMode of ["none", "fields", "generic"] as const) {
  test(`node hover run handles ${inputMode} inputs and stops at its target`, async ({ page }, testInfo) => {
    const hasInput = inputMode !== "none";
    const workflow = await createWorkflow(page, `Node Run ${inputMode} ${Date.now()}`, [
      ...(hasInput ? [{ id: "input", type: "textInput", position: { x: 20, y: 100 },
        data: { label: "start", inputFields: [{ key: "text" }, { key: "extra" }] } }] : []),
      { id: "target", type: "set", position: { x: 280, y: 100 },
        data: { label: "transform", mappings: [{ key: "text", value: hasInput ? "$start.body.text.toUpperCase()" : "ready" }] } },
      { id: "later", type: "throwError", position: { x: 540, y: 100 },
        data: { label: "later", errorMessage: "Must not execute" } },
      { id: "other", type: "textInput", position: { x: 20, y: 300 },
        data: { label: "unrelated", inputFields: [{ key: "unrelated" }] } },
      { id: "note", type: "sticky", position: { x: 540, y: 350 },
        data: { label: "note", content: "A note" } },
    ], [
      ...(hasInput ? [{ id: "a", source: "input", target: "target" }] : []),
      { id: "b", source: "target", target: "later" },
    ]);
    try {
      if (inputMode === "generic") {
        const update = await page.request.put(`/api/workflows/${workflow.id}`, {
          data: { webhook_body_mode: "generic" },
        });
        expect(update.ok()).toBe(true);
      }
      await page.goto(`/workflows/${workflow.id}`);
      await expect(page.locator(".vue-flow__node")).toHaveCount(hasInput ? 5 : 4);
      await page.locator(".panel-toggle-right").click();
      await expect(page.locator(".properties-panel")).toHaveCount(0);
      const target = page.locator('.vue-flow__node[data-id="target"]');
      const button = target.getByRole("button", { name: "Run to transform", exact: true });
      await page.mouse.move(0, 0);
      await expect(target.locator(".canvas-node-run")).toHaveCSS("opacity", "0");
      // Closing the panel triggers a canvas fit; follow the node until that settles.
      await expect(async () => {
        await target.hover();
        await expect(target.locator(".canvas-node-run")).toHaveCSS("opacity", "1", { timeout: 500 });
      }).toPass({ timeout: 8_000 });
      await page.screenshot({ path: testInfo.outputPath("node-hover.png") });
      await expect(page.locator('.vue-flow__node[data-id="note"] .canvas-node-run')).toHaveCount(0);
      if (hasInput) {
        await button.click();
        const panel = page.locator(".properties-panel");
        await expect(panel).toBeVisible();
        await expect(panel.locator("textarea").first()).toBeFocused();
        if (inputMode === "fields") {
          await panel.getByRole("button", { name: "Properties", exact: true }).click();
          await target.hover();
          await button.click();
          await expect(panel.locator("textarea").first()).toBeFocused();
        }
        await page.screenshot({ path: testInfo.outputPath("focused-run-input.png") });
        await expect(page.getByPlaceholder("Enter unrelated...")).toHaveCount(0);
        await expect(target).not.toHaveClass(/selected/);
        if (inputMode === "generic") {
          await panel.locator("textarea").first().fill('{"text":"hello"}');
        } else {
          await page.getByPlaceholder("Enter text...").fill("hello");
        }
        const resultPromise = completion(page, workflow.id);
        if (inputMode === "generic") {
          await page.keyboard.press("Control+Enter");
        } else {
          await panel.getByRole("button", { name: "Run to transform", exact: true }).click();
        }
        const result = await resultPromise;
        expect(result.status).toBe("success");
        expect(result.node_results.map((row) => row.node_id)).toEqual(["input", "target"]);
        expect(result.node_results.at(-1)?.output.text).toBe("HELLO");
      } else {
        const resultPromise = completion(page, workflow.id);
        await button.click();
        const result = await resultPromise;
        expect(result.status).toBe("success");
        expect(result.node_results.map((row) => row.node_id)).toEqual(["target"]);
        await expect(page.locator(".properties-panel")).toHaveCount(0);
      }
    } finally {
      await deleteWorkflow(page, workflow.id);
    }
  });
}
