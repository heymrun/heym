import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows the traces empty state and filter controls", async ({ page }) => {
  await page.goto("/?tab=traces");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Traces", exact: true })).toBeVisible();
  await expect(main.getByText("No traces yet.", { exact: true })).toBeVisible();
  await expect(main.getByText("Time range", { exact: true })).toBeVisible();
  await expect(main.getByRole("button", { name: "Refresh" })).toBeVisible();
});

test("reloads traces on time range change and toggles the search box", async ({ page }) => {
  await page.goto("/?tab=traces");
  await expect(page.getByRole("main").getByRole("heading", { name: "Traces" })).toBeVisible();

  // Changing the time range refetches traces with the new range.
  const tracesReloadPromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === "/api/traces",
  );
  await page.locator('select:has(option[value="1h"])').selectOption("24h");
  expect((await tracesReloadPromise).ok()).toBeTruthy();

  // The search box is collapsed by default; the toggle (the icon button before
  // Refresh) reveals it, accepts text, and exposes a clear button.
  const searchToggle = page
    .getByRole("button", { name: "Refresh" })
    .locator("xpath=preceding-sibling::button[1]");
  await searchToggle.click();

  const search = page.getByPlaceholder("Search traces by model, workflow, credential, node...");
  await expect(search).toBeVisible();
  await search.fill("gpt-4o");
  await expect(search).toHaveValue("gpt-4o");
  const clearButton = search.locator("xpath=following-sibling::button");
  await expect(clearButton).toBeVisible();
  await clearButton.click();
  await expect(search).toHaveValue("");
});

test("renders JSON trace events as expandable trees with a raw toggle", async ({ page }) => {
  const traceId = "11111111-1111-4111-8111-111111111111";
  const createdAt = "2026-07-20T12:00:00Z";
  const jsonRpcEvent = JSON.stringify({
    jsonrpc: "2.0",
    method: "tools/call",
    params: {
      name: "catalog.search",
      arguments: { query: "wireless headphones", filters: { in_stock: true } },
    },
  });

  const trace = {
    id: traceId,
    created_at: createdAt,
    source: "workflow",
    request_type: "chat.completions",
    provider: "OpenAI",
    model: "gpt-4.1-mini",
    credential_id: null,
    credential_name: "Test credential",
    workflow_id: null,
    workflow_name: "JSON event workflow",
    node_id: "agent-1",
    node_label: "Catalog Agent",
    status: "success",
    elapsed_ms: 842,
    prompt_tokens: 40,
    completion_tokens: 20,
    total_tokens: 60,
    cost_usd: "0.0012",
    is_priced: true,
  };

  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      json: {
        id: "22222222-2222-4222-8222-222222222222",
        email: "trace-json@example.com",
        name: "Trace JSON Test",
        user_rules: null,
        tts_credential_id: null,
        tts_voice_id: null,
        preferred_credential_id: null,
        preferred_model: null,
        created_at: createdAt,
      },
    });
  });
  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/workflows/with-inputs", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/workflows", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/folders/tree", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/templates**", async (route) => {
    await route.fulfill({ json: { workflow_templates: [], node_templates: [] } });
  });
  await page.route("**/api/traces**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/traces/stats") {
      await route.fulfill({
        json: {
          range: { start: null, end: createdAt, bucket_seconds: 3600 },
          kpis: {
            total_calls: 1,
            success_calls: 1,
            error_calls: 0,
            error_pct: 0,
            prompt_tokens: 40,
            completion_tokens: 20,
            total_tokens: 60,
            total_cost_usd: "0.0012",
            avg_latency_ms: 842,
            unpriced_models: [],
          },
          by_model: [],
          by_time: [],
        },
      });
      return;
    }
    if (pathname === `/api/traces/${traceId}`) {
      await route.fulfill({
        json: {
          ...trace,
          request: {
            messages: [
              { role: "user", content: jsonRpcEvent },
              {
                role: "assistant",
                content: "Calling the catalog tool.",
                tool_calls: [
                  {
                    id: "call-1",
                    type: "function",
                    function: {
                      name: "catalog.search",
                      arguments: JSON.stringify({
                        query: "wireless headphones",
                        filters: { in_stock: true },
                      }),
                    },
                  },
                ],
              },
              {
                role: "tool",
                tool_call_id: "call-1",
                content: JSON.stringify({
                  jsonrpc: "2.0",
                  result: { items: [{ id: 7, metadata: { rating: 4.8 } }] },
                }),
              },
            ],
          },
          response: {
            text: "Found one matching item.",
            elapsed_ms: 842,
            usage: { total_tokens: 60 },
            tool_calls: [
              {
                id: "call-1",
                name: "catalog.search",
                arguments: {
                  query: "wireless headphones",
                  filters: { in_stock: true },
                },
                result: {
                  jsonrpc: "2.0",
                  result: { items: [{ id: 7, metadata: { rating: 4.8 } }] },
                },
                elapsed_ms: 210,
                source: "mcp",
                mcp_server: "Catalog",
              },
            ],
          },
          error: null,
        },
      });
      return;
    }
    if (pathname === "/api/traces") {
      await route.fulfill({ json: { items: [trace], total: 1, limit: 25, offset: 0 } });
      return;
    }
    await route.continue();
  });

  await page.goto("/?tab=traces");
  await page.getByRole("button", { name: /JSON event workflow/ }).click();
  await expect(page.getByText("Trace Details", { exact: true })).toBeVisible();

  const userStep = page.getByTestId("trace-step-msg-0");
  await userStep.getByRole("button").first().click();
  const userJson = userStep.getByTestId("trace-json-content").first();

  await expect(userJson.getByRole("button", { name: "Tree" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(userJson.getByText("jsonrpc:", { exact: true })).toBeVisible();
  await expect(userJson.getByText("name:", { exact: true })).toBeVisible();
  await expect(userJson.getByText("query:", { exact: true })).toBeVisible();
  await expect(userJson.getByText("in_stock:", { exact: true })).toBeHidden();

  await userJson.getByText("filters:", { exact: true }).click();
  await expect(userJson.getByText("in_stock:", { exact: true })).toBeVisible();
  await userJson.getByText("params:", { exact: true }).click();
  await expect(userJson.getByText("name:", { exact: true })).toBeHidden();
  await userJson.getByText("params:", { exact: true }).click();

  await userJson.getByRole("button", { name: "Raw" }).click();
  await expect(userJson.getByRole("button", { name: "Raw" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(userJson.locator("pre")).toContainText('"jsonrpc":"2.0"');
  await userJson.getByRole("button", { name: "Tree" }).click();

  const toolStep = page.getByTestId("trace-step-tool-call-1");
  await toolStep.getByRole("button").first().click();
  const toolJsonViews = toolStep.getByTestId("trace-json-content");
  await expect(toolJsonViews.nth(0).getByText("query:", { exact: true })).toBeVisible();
  await expect(toolJsonViews.nth(1).getByText("jsonrpc:", { exact: true })).toBeVisible();

  await toolStep.scrollIntoViewIfNeeded();
  await page.screenshot({ path: ".e2e-artifacts/traces-json-tree.png" });
});
