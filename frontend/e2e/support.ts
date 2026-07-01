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

export interface TestDataTable {
  id: string;
  name: string;
}

export async function createDataTable(
  page: Page,
  name: string,
  columns: Record<string, unknown>[] = [],
): Promise<TestDataTable> {
  const response = await page.request.post("/api/data-tables", {
    data: { name, description: "Created by Playwright", columns },
  });
  await expectOk(response);
  return (await response.json()) as TestDataTable;
}

export async function deleteDataTable(page: Page, tableId: string): Promise<void> {
  const response = await page.request.delete(`/api/data-tables/${tableId}`);
  expect([204, 404]).toContain(response.status());
}

export async function clearDriveFiles(page: Page): Promise<void> {
  const response = await page.request.delete("/api/files");
  expect([204, 404]).toContain(response.status());
}

export async function uploadDriveFile(
  page: Page,
  filename: string,
  contents: string,
): Promise<{ id: string }> {
  const response = await page.request.post("/api/files/upload", {
    multipart: {
      file: {
        name: filename,
        mimeType: "text/plain",
        buffer: Buffer.from(contents),
      },
    },
  });
  await expectOk(response);
  return (await response.json()) as { id: string };
}

export async function createDashboardWidget(
  page: Page,
  title: string,
  chartType = "bar",
): Promise<{ id: string; workflow_id: string }> {
  const response = await page.request.post("/api/dashboards/widgets", {
    data: {
      title,
      description: null,
      chart_type: chartType,
      layout: { x: 0, y: 0, w: 4, h: 4 },
      cache_ttl_seconds: 300,
    },
  });
  await expectOk(response);
  return (await response.json()) as { id: string; workflow_id: string };
}

export async function deleteDashboardWidget(page: Page, widgetId: string): Promise<void> {
  const response = await page.request.delete(`/api/dashboards/widgets/${widgetId}`);
  expect([204, 404]).toContain(response.status());
}

export async function clearDashboardWidgets(page: Page): Promise<void> {
  const response = await page.request.get("/api/dashboards");
  await expectOk(response);
  const dashboard = (await response.json()) as { widgets?: { id: string }[] };
  for (const widget of dashboard.widgets ?? []) {
    await deleteDashboardWidget(page, widget.id);
  }
}

export async function deleteTeam(page: Page, teamId: string): Promise<void> {
  const response = await page.request.delete(`/api/teams/${teamId}`);
  expect([204, 404]).toContain(response.status());
}

export async function deleteEvalSuite(page: Page, suiteId: string): Promise<void> {
  const response = await page.request.delete(`/api/evals/suites/${suiteId}`);
  expect([204, 404]).toContain(response.status());
}

export async function clearEvalSuites(page: Page): Promise<void> {
  const response = await page.request.get("/api/evals/suites");
  await expectOk(response);
  const suites = (await response.json()) as { id: string }[];
  for (const suite of suites) {
    await deleteEvalSuite(page, suite.id);
  }
}

export async function deleteCredential(page: Page, credentialId: string): Promise<void> {
  const response = await page.request.delete(`/api/credentials/${credentialId}`);
  expect([204, 404]).toContain(response.status());
}

export async function deleteMcpServer(page: Page, serverId: string): Promise<void> {
  const response = await page.request.delete(`/api/mcp/servers/${serverId}`);
  expect([204, 404]).toContain(response.status());
}

export async function createWorkflowTemplate(
  page: Page,
  name: string,
): Promise<{ id: string }> {
  const response = await page.request.post("/api/templates", {
    data: {
      kind: "workflow",
      workflow: {
        name,
        description: "Playwright template",
        tags: ["e2e"],
        nodes: [],
        edges: [],
        visibility: "everyone",
      },
    },
  });
  await expectOk(response);
  return (await response.json()) as { id: string };
}

export async function deleteWorkflowTemplate(page: Page, templateId: string): Promise<void> {
  const response = await page.request.delete(`/api/templates/workflow/${templateId}`);
  expect([204, 404]).toContain(response.status());
}

export async function expectOk(response: APIResponse): Promise<void> {
  expect(response.ok(), await response.text()).toBeTruthy();
}

export async function selectSearchableOption(
  page: Page,
  field: import("@playwright/test").Locator,
  optionLabel: string,
): Promise<void> {
  const combobox = field.getByRole("combobox");
  await combobox.click();
  await combobox.fill(optionLabel);
  const listboxId = await combobox.getAttribute("aria-controls");
  const listbox = listboxId
    ? page.locator(`#${listboxId}`)
    : page.getByRole("listbox").filter({ has: page.getByRole("option", { name: optionLabel }) });
  await listbox.getByRole("option", { name: optionLabel, exact: true }).click();
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
