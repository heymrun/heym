import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

async function createConversation(page: import("@playwright/test").Page): Promise<string> {
  await page.getByRole("button", { name: "New Chat", exact: true }).click();
  await expect(page).toHaveURL(/\/chats\/[0-9a-f-]+$/);
  const conversationId = page.url().split("/").pop();
  expect(conversationId).toBeTruthy();
  return conversationId as string;
}

test("creates a conversation and renames it", async ({ page }) => {
  const renamedTitle = `Renamed Chat ${Date.now()}`;

  await page.goto("/chats");
  await expect(page.getByText("Ask to run a workflow")).toBeVisible();

  const conversationId = await createConversation(page);
  const item = page.getByTestId(`chat-list-item-${conversationId}`);
  await expect(item).toBeVisible();

  // Rename via the hover action, commit with Enter.
  await item.hover();
  await item.getByTitle("Rename").click();
  const renameInput = item.locator("input");
  await renameInput.fill(renamedTitle);
  await renameInput.press("Enter");
  await expect(item).toContainText(renamedTitle);

  // The rename is server-persisted and survives a reload.
  await page.reload();
  await expect(page.getByTestId(`chat-list-item-${conversationId}`)).toContainText(renamedTitle);
});

test("creates and deletes a conversation", async ({ page }) => {
  await page.goto("/chats");
  await expect(page.getByText("Ask to run a workflow")).toBeVisible();

  const conversationId = await createConversation(page);
  const item = page.getByTestId(`chat-list-item-${conversationId}`);
  await expect(item).toBeVisible();

  await item.hover();
  await item.getByTitle("Delete").click();
  await item.getByTitle("Confirm delete").click();
  await expect(page).toHaveURL(/\/chats$/);
  await expect(page.getByTestId(`chat-list-item-${conversationId}`)).toHaveCount(0);
});
