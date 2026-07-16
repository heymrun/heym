import { expect, test } from "@playwright/test";

import { acceptNextDialog, deleteMcpServer, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows the MCP connection config and named servers section", async ({ page }) => {
  await page.goto("/?tab=mcp");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "MCP Server", exact: true })).toBeVisible();
  await expect(main.getByRole("heading", { name: "MCP Connection" })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Named MCP Servers" })).toBeVisible();
  await expect(
    page.getByPlaceholder("Server name (e.g. CRM Tools)"),
  ).toBeVisible();
});

test("sorts only named servers by selected workflows and recent updates", async ({ page }) => {
  const workflows = [
    {
      id: "workflow-unselected-newest",
      name: "Unselected Newest Workflow",
      description: null,
      mcp_enabled: false,
      input_fields: [],
      updated_at: "2026-06-01T00:00:00Z",
    },
    {
      id: "workflow-selected-older",
      name: "Selected Older Workflow",
      description: null,
      mcp_enabled: true,
      input_fields: [],
      updated_at: "2026-03-01T00:00:00Z",
    },
    {
      id: "workflow-selected-newer",
      name: "Selected Newer Workflow",
      description: null,
      mcp_enabled: true,
      input_fields: [],
      updated_at: "2026-05-01T00:00:00Z",
    },
    {
      id: "workflow-unselected-older",
      name: "Unselected Older Workflow",
      description: null,
      mcp_enabled: false,
      input_fields: [],
      updated_at: "2026-01-01T00:00:00Z",
    },
  ];
  const servers = [
    {
      id: "server-unselected-newest",
      name: "Unselected Newest Server",
      api_key: "unselected-newest-api-key",
      created_at: "2026-01-01T00:00:00Z",
      workflow_ids: ["workflow-unselected-newest"],
      workflows: [],
    },
    {
      id: "server-selected-older",
      name: "Selected Older Server",
      api_key: "selected-older-api-key",
      created_at: "2026-01-02T00:00:00Z",
      workflow_ids: ["workflow-selected-older"],
      workflows: [],
    },
    {
      id: "server-empty",
      name: "Empty Server",
      api_key: "empty-server-api-key",
      created_at: "2026-01-03T00:00:00Z",
      workflow_ids: [],
      workflows: [],
    },
    {
      id: "server-selected-newer",
      name: "Selected Newer Server",
      api_key: "selected-newer-api-key",
      created_at: "2026-01-04T00:00:00Z",
      workflow_ids: ["workflow-selected-newer"],
      workflows: [],
    },
    {
      id: "server-unselected-older",
      name: "Unselected Older Server",
      api_key: "unselected-older-api-key",
      created_at: "2026-01-05T00:00:00Z",
      workflow_ids: ["workflow-unselected-older"],
      workflows: [],
    },
  ];

  await page.route("**/api/mcp/config", async (route) => {
    await route.fulfill({
      json: {
        mcp_api_key: "test-mcp-api-key",
        mcp_endpoint_url: "http://localhost/api/mcp/sse",
        workflows,
      },
    });
  });
  await page.route("**/api/mcp/servers", async (route) => {
    await route.fulfill({ json: { servers } });
  });

  await page.goto("/?tab=mcp");

  await expect(page.locator("p.font-medium.text-sm.truncate")).toHaveText([
    "Selected Newer Server",
    "Selected Older Server",
    "Unselected Newest Server",
    "Unselected Older Server",
    "Empty Server",
  ]);
  await expect(page.locator("h4.font-medium.truncate")).toHaveText(
    workflows.map((workflow) => workflow.name),
  );
});

test("creates a named MCP server, reveals its endpoint, and deletes it", async ({ page }) => {
  const serverName = `E2E MCP ${Date.now()}`;

  await page.goto("/?tab=mcp");
  await expect(
    page.getByText("No named servers yet. Create one to get a dedicated MCP endpoint."),
  ).toBeVisible();

  // Create the server (Enter submits the inline form).
  const serverResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/mcp/servers",
  );
  const nameInput = page.getByPlaceholder("Server name (e.g. CRM Tools)");
  await nameInput.fill(serverName);
  await nameInput.press("Enter");
  const server = (await (await serverResponsePromise).json()) as { id: string };

  try {
    const serverCard = page.getByText(serverName, { exact: true });
    await expect(serverCard).toBeVisible();

    // Expanding the server reveals its dedicated SSE endpoint.
    await serverCard.click();
    await expect(page.getByText("SSE Endpoint")).toBeVisible();

    // Delete via the confirm dialog returns to the empty state.
    await acceptNextDialog(
      page,
      () => page.getByTitle("Delete server").click(),
      `Delete server "${serverName}"? This cannot be undone.`,
    );
    await expect(page.getByText(serverName, { exact: true })).toBeHidden();
  } finally {
    await deleteMcpServer(page, server.id);
  }
});
