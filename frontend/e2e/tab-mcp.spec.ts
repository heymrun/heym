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
