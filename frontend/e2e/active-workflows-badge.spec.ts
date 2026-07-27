import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

interface ActiveExecutionFixture {
  execution_id: string;
  workflow_id: string;
  workflow_name: string;
  started_at: string;
  inputs: Record<string, unknown>;
  running_node_ids: string[];
  node_results: [];
  status?: "running" | "pending";
  pending_kind?: "hitl" | "codex" | null;
}

function makeActiveExecution(
  index: number,
  workflowIndex = index,
  options: { status?: "running" | "pending"; pending_kind?: "hitl" | "codex" } = {},
): ActiveExecutionFixture {
  const suffix = String(index).padStart(12, "0");
  const workflowSuffix = String(workflowIndex).padStart(12, "0");
  const status = options.status ?? "running";
  return {
    execution_id: `10000000-0000-4000-8000-${suffix}`,
    workflow_id: `20000000-0000-4000-8000-${workflowSuffix}`,
    workflow_name:
      status === "pending"
        ? `Pending workflow ${workflowIndex}`
        : `Running workflow ${workflowIndex}`,
    started_at: new Date(Date.UTC(2026, 0, 1, 12, index)).toISOString(),
    inputs: {},
    running_node_ids: status === "pending" ? [] : [`node-${index}`],
    node_results: [],
    status,
    pending_kind: options.pending_kind ?? null,
  };
}

function makeWorkflowFixture(id: string, name: string): Record<string, unknown> {
  const timestamp = new Date(Date.UTC(2026, 0, 1, 12, 0)).toISOString();
  return {
    id,
    name,
    description: null,
    nodes: [],
    edges: [],
    auth_type: "jwt",
    auth_header_key: null,
    auth_header_value: null,
    webhook_body_mode: "legacy",
    allow_anonymous: false,
    owner_id: "00000000-0000-4000-8000-000000000000",
    cache_ttl_seconds: null,
    rate_limit_requests: null,
    rate_limit_window_seconds: null,
    sse_enabled: false,
    sse_node_config: {},
    auto_recover_runs: false,
    error_workflow_id: null,
    minutes_saved_per_run: null,
    workflow_timeout_seconds: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("polls, scrolls active workflows, and opens a live workflow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.install();

  const allActiveExecutions = Array.from({ length: 5 }, (_, index) =>
    makeActiveExecution(index + 1, index < 3 ? 1 : index + 1),
  );
  let activeExecutions = allActiveExecutions.slice(0, 2);
  let requestCount = 0;
  await page.route("**/api/workflows/executions/active", async (route) => {
    requestCount += 1;
    await route.fulfill({ json: activeExecutions });
  });

  // Opening a live workflow navigates to the editor, which loads the workflow and redirects
  // back to the dashboard if that GET fails. The active-execution fixtures use synthetic ids
  // that do not exist in the backend, so stub the workflow load to keep the editor mounted.
  const liveWorkflowId = "20000000-0000-4000-8000-000000000004";
  const liveExecutionId = "10000000-0000-4000-8000-000000000004";
  await page.route(`**/api/workflows/${liveWorkflowId}`, async (route) => {
    await route.fulfill({ json: makeWorkflowFixture(liveWorkflowId, "Running workflow 4") });
  });

  await page.goto("/");

  const badge = page.getByTestId("active-workflows-badge");
  await expect(badge).toHaveText("2");
  await expect(badge).toHaveAttribute("aria-expanded", "false");
  expect(
    await badge.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return Math.abs(bounds.width - bounds.height) < 0.5;
    }),
  ).toBe(true);

  activeExecutions = allActiveExecutions;
  await page.clock.fastForward(10_000);
  await expect.poll(() => requestCount).toBeGreaterThanOrEqual(2);
  await expect(badge).toHaveText("5");

  await badge.click();
  const dropdown = page.getByTestId("active-workflows-dropdown");
  const scrollArea = page.getByTestId("active-workflows-scroll-area");
  await expect(dropdown).toBeVisible();
  await expect(dropdown.getByRole("menuitem")).toHaveCount(5);
  await expect(badge).toHaveAttribute("aria-expanded", "true");
  expect(
    await scrollArea.evaluate((element) => element.scrollHeight > element.clientHeight),
  ).toBe(true);

  await page
    .getByRole("menuitem", { name: "Open Running workflow 4 live view" })
    .click();
  await expect(page).toHaveURL(`/workflows/${liveWorkflowId}/${liveExecutionId}`);
});

test("counts pending HITL reviews in the badge number", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/workflows/executions/active", async (route) => {
    await route.fulfill({
      json: [
        makeActiveExecution(1, 1),
        makeActiveExecution(2, 2, { status: "pending", pending_kind: "hitl" }),
        makeActiveExecution(3, 3, { status: "pending", pending_kind: "codex" }),
      ],
    });
  });

  await page.goto("/");

  const badge = page.getByTestId("active-workflows-badge");
  await expect(badge).toHaveText("3");
  await expect(badge).toHaveAttribute("title", "1 running · 2 pending reviews");

  await badge.click();
  const dropdown = page.getByTestId("active-workflows-dropdown");
  await expect(dropdown).toBeVisible();
  await expect(dropdown.getByText("Pending human review")).toHaveCount(1);
  await expect(dropdown.getByText("Pending Codex review")).toHaveCount(1);
});

test("keeps the zero state non-interactive and hides the badge on mobile", async ({ page }) => {
  await page.route("**/api/workflows/executions/active", async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const counter = page.getByTestId("active-workflows-counter");
  await expect(counter).toHaveCSS("height", "0px");
  await expect(counter.getByRole("button")).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(counter).toHaveCount(0);
});

test("shows a non-interactive error badge when the initial refresh fails", async ({ page }) => {
  await page.route("**/api/workflows/executions/active", async (route) => {
    await route.fulfill({
      status: 503,
      json: { detail: "Active workflow status is temporarily unavailable" },
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const counter = page.getByTestId("active-workflows-counter");
  await expect(page.getByTestId("active-workflows-badge-error")).toBeVisible();
  await expect(counter.getByRole("button")).toHaveCount(0);
});
