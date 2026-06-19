import { expect, type APIResponse, type Page } from "@playwright/test";

export const E2E_USER = {
  email: "playwright@heym.example.com",
  password: "Playwright123",
};

export interface TestWorkflow {
  id: string;
  name: string;
}

export async function mockVersionCheck(page: Page): Promise<void> {
  await page.route("**/api/version**", async (route) => {
    await route.fulfill({
      json: {
        version: "0.0.46",
        latest_version: null,
        update_available: false,
        release_url: null,
        compare_url: null,
        compare_label: null,
        source: "e2e",
        checked_at: null,
        error: null,
      },
    });
  });
}

export async function prepareAuthenticatedPage(page: Page): Promise<void> {
  await mockVersionCheck(page);
  await page.addInitScript(() => {
    const showcaseKeys = [
      "dashboard_workflows",
      "dashboard_templates",
      "dashboard_globalvariables",
      "dashboard_chat",
      "dashboard_drive",
      "dashboard_datatable",
      "dashboard_schedules",
      "dashboard_credentials",
      "dashboard_vectorstores",
      "dashboard_mcp",
      "dashboard_traces",
      "dashboard_analytics",
      "dashboard_dashboard",
      "dashboard_teams",
      "dashboard_logs",
      "evals",
      "docs",
      "editor",
    ];
    for (const key of showcaseKeys) {
      window.localStorage.setItem(`showcase_seen_${key}`, "1");
    }
  });
}

export async function createWorkflow(
  page: Page,
  name: string,
  nodes: Record<string, unknown>[] = [],
  edges: Record<string, unknown>[] = [],
): Promise<TestWorkflow> {
  const createResponse = await page.request.post("/api/workflows", {
    data: { name, description: "Created by Playwright" },
  });
  expect(createResponse.ok()).toBeTruthy();
  const workflow = await createResponse.json() as TestWorkflow;
  if (nodes.length > 0 || edges.length > 0) {
    const updateResponse = await page.request.put(`/api/workflows/${workflow.id}`, {
      data: { nodes, edges },
    });
    expect(updateResponse.ok()).toBeTruthy();
  }
  return workflow;
}

export async function deleteWorkflow(page: Page, workflowId: string): Promise<void> {
  const response = await page.request.delete(`/api/workflows/${workflowId}`);
  expect([204, 404]).toContain(response.status());
}

export async function expectOk(response: APIResponse): Promise<void> {
  expect(response.ok(), await response.text()).toBeTruthy();
}

export async function acceptNextDialog(
  page: Page,
  action: () => Promise<void>,
  expectedMessage: string | RegExp,
): Promise<void> {
  const dialogPromise = page.waitForEvent("dialog");
  const actionPromise = action();
  const dialog = await dialogPromise;
  if (typeof expectedMessage === "string") {
    expect(dialog.message()).toBe(expectedMessage);
  } else {
    expect(dialog.message()).toMatch(expectedMessage);
  }
  await dialog.accept();
  await actionPromise;
}
