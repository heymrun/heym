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

test("queues, edits, and deletes a message while streaming", async ({ page }) => {
  const conversationId = "11111111-1111-4111-8111-111111111111";
  const credentialId = "22222222-2222-4222-8222-222222222222";
  const queuedId = "33333333-3333-4333-8333-333333333333";
  const now = new Date().toISOString();
  let queuedContent = "Second queued message";

  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({
      json: [
        {
          id: credentialId,
          name: "Mock OpenAI",
          type: "openai",
          masked_value: "sk-...",
          header_key: null,
          created_at: now,
        },
      ],
    });
  });
  await page.route(`**/api/credentials/${credentialId}/models`, async (route) => {
    await route.fulfill({
      json: [
        {
          id: "gpt-4o",
          name: "GPT-4o",
          is_reasoning: false,
          supports_batch: false,
          batch_support_reason: null,
          context_window: 128000,
        },
      ],
    });
  });
  await page.route("**/api/chats/quick-prompts", async (route) => {
    await route.fulfill({ json: { prompts: ["List my workflows"] } });
  });
  await page.route(`**/api/chats/${conversationId}/context-summary**`, async (route) => {
    await route.fulfill({
      json: {
        used: 100,
        limit: 1000,
        breakdown: {
          system: 10,
          agents_md: 10,
          workflows: 10,
          user_rules: 10,
          history: 10,
          attachment: 0,
        },
      },
    });
  });
  await page.route(`**/api/chats/${conversationId}/read`, async (route) => {
    await route.fulfill({ status: 204 });
  });
  await page.route(`**/api/chats/${conversationId}/stream`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body: 'data: {"type":"content","text":"Thinking","message_id":"44444444-4444-4444-8444-444444444444"}\n\n',
    });
  });
  await page.route(`**/api/chats/${conversationId}/messages`, async (route) => {
    const body = await route.request().postDataJSON() as { content: string };
    queuedContent = body.content;
    await route.fulfill({
      status: 202,
      json: {
        conversation_id: conversationId,
        status: "queued",
        user_message: null,
        queued_message: {
          id: queuedId,
          content: queuedContent,
          credential_id: credentialId,
          model: "gpt-4o",
          attachment_name: null,
          created_at: now,
          updated_at: now,
        },
      },
    });
  });
  await page.route(`**/api/chats/${conversationId}/queue/${queuedId}`, async (route) => {
    if (route.request().method() === "PATCH") {
      const body = await route.request().postDataJSON() as { content: string };
      queuedContent = body.content;
      await route.fulfill({
        json: {
          id: queuedId,
          content: queuedContent,
          credential_id: credentialId,
          model: "gpt-4o",
          attachment_name: null,
          created_at: now,
          updated_at: new Date().toISOString(),
        },
      });
      return;
    }
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/chats", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      json: {
        conversations: [
          {
            id: conversationId,
            title: "Streaming Chat",
            is_pinned: false,
            is_running: true,
            has_unread: false,
            created_at: now,
            updated_at: now,
          },
        ],
      },
    });
  });
  await page.route(`**/api/chats/${conversationId}`, async (route) => {
    await route.fulfill({
      json: {
        id: conversationId,
        title: "Streaming Chat",
        is_pinned: false,
        is_running: true,
        has_unread: false,
        last_credential_id: credentialId,
        last_model: "gpt-4o",
        created_at: now,
        updated_at: now,
        messages: [
          {
            id: "55555555-5555-4555-8555-555555555555",
            role: "user",
            content: "First message",
            created_at: now,
            tool_calls: null,
          },
        ],
        queued_messages: [],
      },
    });
  });

  await page.goto(`/chats/${conversationId}`);
  await expect(page.getByText("Thinking")).toBeVisible();
  const textbox = page.getByPlaceholder("Type a message...");
  await expect(textbox).toBeEnabled();
  await textbox.fill("Second queued message");
  await page.getByRole("button", { name: "Send message" }).click();

  const inputArea = page.locator(".chat-input-area");
  await expect(inputArea.getByText("Queue", { exact: true })).toBeVisible();
  await expect(inputArea.getByText("Second queued message", { exact: true })).toBeVisible();
  await expect(
    page.locator("#chat-messages-scroll").getByText("Second queued message", { exact: true }),
  ).toHaveCount(0);

  await page.getByTitle("Edit queued message").click();
  await page.locator("[data-queued-edit]").fill("Updated queued message");
  await page.getByTitle("Save queued message").click();
  await expect(inputArea.getByText("Updated queued message", { exact: true })).toBeVisible();

  await page.getByTitle("Delete queued message").click();
  await expect(inputArea.getByText("Updated queued message", { exact: true })).toHaveCount(0);
});
