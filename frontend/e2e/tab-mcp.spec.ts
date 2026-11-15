import { expect, test } from "@playwright/test";

import {
  acceptNextDialog,
  deleteMcpServer,
  expectInsideViewport,
  prepareAuthenticatedPage,
} from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows the MCP connection config and named servers section", async ({ page }) => {
  await page.goto("/?tab=mcp");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "MCP / A2A", exact: true })).toBeVisible();
  await expect(main.getByRole("heading", { name: "MCP Connection" })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Named MCP Servers" })).toBeVisible();
  await expect(
    page.getByPlaceholder("Server name (e.g. CRM Tools)"),
  ).toBeVisible();
});

test("sends ChatGPT users to Plugins to add Heym as a custom MCP server", async ({ page }) => {
  await page.goto("/?tab=mcp");
  const main = page.getByRole("main");
  await main.getByRole("button", { name: "ChatGPT Connector", exact: true }).click();

  await expect(main.getByText("chatgpt.com/plugins", { exact: true })).toBeVisible();
  await expect(main.getByText("Create as a plugin", { exact: true })).toBeVisible();
  await expect(main.getByText("Settings → Security and login", { exact: true })).toBeVisible();
  await expect(main.getByText("Apps → Advanced settings")).toHaveCount(0);
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

    // The newly created server is expanded automatically; verify its dedicated MCP endpoint.
    await expect(page.getByText("MCP Endpoint", { exact: true })).toBeVisible();
    await expect(page.getByText(new RegExp(`/api/mcp/servers/${server.id}/mcp$`))).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy JSON" }).last()).toBeVisible();

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

test("shows the default MCP connection config at /api/mcp", async ({ page }) => {
  await page.goto("/?tab=mcp");
  const main = page.getByRole("main");
  await expect(main.getByText("MCP Endpoint URL", { exact: true })).toBeVisible();
  await expect(main.getByText(/\/api\/mcp$/)).toBeVisible();
  await expect(main.locator("pre").filter({ hasText: '"url":' })).toContainText("/api/mcp");
});

test("legacy named server with endpoint_path = 'sse' displays /sse URL and generated config", async ({ page }) => {
  const legacyServerId = "00000000-0000-0000-0000-000000000001";
  await page.route("**/api/mcp/servers", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          servers: [
            {
              id: legacyServerId,
              name: "Legacy Server",
              api_key: null,
              api_key_set: true,
              created_at: new Date().toISOString(),
              workflow_ids: [],
              endpoint_path: "sse",
              chat_tool: {
                enabled: false,
                credential_id: null,
                model: null,
                a2a_enabled: false,
              },
            },
          ],
        }),
      });
    } else {
      await route.continue();
    }
  });

  await page.goto("/?tab=mcp");
  const serverCard = page.getByText("Legacy Server", { exact: true });
  await expect(serverCard).toBeVisible();
  await serverCard.click();
  await expect(page.getByText("MCP Endpoint", { exact: true })).toBeVisible();
  await expect(page.getByText(new RegExp(`/api/mcp/servers/${legacyServerId}/sse$`))).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy JSON" }).last()).toBeVisible();
});

test("lays out the MCP connection card for a phone screen", async ({ page }) => {
  const viewportWidth = 390;
  await page.setViewportSize({ width: viewportWidth, height: 844 });
  await page.goto("/?tab=mcp");

  const main = page.getByRole("main");
  const heading = await expectInsideViewport(
    main.getByRole("heading", { name: "MCP Connection" }),
    viewportWidth,
  );
  const apiKeyTab = await expectInsideViewport(
    main.getByRole("button", { name: "API Key", exact: true }),
    viewportWidth,
  );
  // The icon sits beside the heading, so the tabs below start left of it rather than under it.
  expect(apiKeyTab.x).toBeLessThan(heading.x);

  for (const tabName of ["Claude Connector", "ChatGPT Connector", "Gemini App"]) {
    await expectInsideViewport(main.getByRole("button", { name: tabName, exact: true }), viewportWidth);
  }
});
