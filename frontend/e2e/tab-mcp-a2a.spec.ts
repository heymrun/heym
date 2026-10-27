import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("opens the MCP / A2A tab from /a2a", async ({ page }) => {
  await page.goto("/a2a");

  await expect(page).toHaveURL(/\?tab=mcp$/);
  await expect(
    page.getByRole("main").getByRole("heading", { name: "MCP / A2A", exact: true }),
  ).toBeVisible();
});

test("enables A2A on the global server and serves its Agent Card", async ({ page }) => {
  await page.goto("/?tab=a2a");
  await expect(page).toHaveURL(/\?tab=mcp$/);
  const card = page.getByTestId("mcp-chat-tool-controls").first();
  const agentToggle = card.getByTestId("mcp-chat-tool-toggle");
  await expect(agentToggle).toBeVisible();

  const wasOn = (await agentToggle.getAttribute("aria-pressed")) === "true";
  try {
    if (!wasOn) {
      await agentToggle.click();
      await expect(agentToggle).toHaveAttribute("aria-pressed", "true");
    }
    const a2aToggle = card.getByTestId("mcp-a2a-toggle");
    if (!(await a2aToggle.isChecked())) {
      const saved = page.waitForResponse(
        (response) =>
          response.request().method() === "PATCH" &&
          new URL(response.url()).pathname === "/api/mcp/chat-tool",
      );
      await a2aToggle.check();
      expect((await saved).status()).toBe(200);
    }

    await expect(card.getByTestId("mcp-a2a-card-url")).toHaveText(
      /\/\.well-known\/agent-card\.json$/,
    );
    await expect(card.getByTestId("mcp-a2a-endpoint-url")).toHaveText(/\/api\/a2a$/);

    const response = await page.request.get("/.well-known/agent-card.json");
    expect(response.status()).toBe(200);
    const body = (await response.json()) as {
      name: string;
      supportedInterfaces: { url: string }[];
    };
    expect(body.name).toBe("Heym Agent");
    expect(body.supportedInterfaces[0].url).toMatch(/\/api\/a2a$/);
  } finally {
    const a2aToggle = card.getByTestId("mcp-a2a-toggle");
    if ((await a2aToggle.isVisible()) && (await a2aToggle.isChecked())) {
      await a2aToggle.uncheck();
    }
    if (!wasOn && (await agentToggle.getAttribute("aria-pressed")) === "true") {
      await agentToggle.click();
    }
  }
});
