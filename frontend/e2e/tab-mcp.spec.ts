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
