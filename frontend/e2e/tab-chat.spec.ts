import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage, selectSearchableOption } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("renders persisted pending, timeout, and cancelled tool statuses", async ({ page }) => {
  const conversationId = "11111111-1111-4111-8111-111111111119";
  const credentialId = "22222222-2222-4222-8222-222222222229";
  const now = "2026-07-27T12:00:00Z";
  const toolCalls = [
    {
      id: "tool-pending",
      name: "wait_for_review",
      label: "Waiting for review",
      args: {},
      response_summary: "Approval required",
      status: "pending",
    },
    {
      id: "tool-timeout",
      name: "slow_tool",
      label: "Slow tool",
      args: {},
      response_summary: "Operation timed out",
      status: "timeout",
    },
    {
      id: "tool-cancelled",
      name: "cancelled_tool",
      label: "Cancelled tool",
      args: {},
      response_summary: "Cancelled",
      status: "cancelled",
    },
  ];

  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/workflows", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/chats", async (route) => {
    await route.fulfill({
      json: {
        conversations: [
          {
            id: conversationId,
            title: "Lifecycle Chat",
            is_pinned: false,
            is_running: false,
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
        title: "Lifecycle Chat",
        is_pinned: false,
        is_running: false,
        has_unread: false,
        last_credential_id: credentialId,
        last_model: "gpt-4o",
        created_at: now,
        updated_at: now,
        queued_messages: [],
        messages: [
          {
            id: "33333333-3333-4333-8333-333333333339",
            role: "assistant",
            content: "Tool lifecycle summary",
            created_at: now,
            tool_calls: toolCalls,
          },
        ],
      },
    });
  });

  await page.goto(`/chats/${conversationId}`);

  const pending = page.getByText("Waiting for review").locator("..");
  const timeout = page.getByText("Slow tool").locator("..");
  const cancelled = page.getByText("Cancelled tool").locator("..");
  await expect(pending.locator(".lucide-clock-3")).toBeVisible();
  await expect(timeout.locator(".lucide-triangle-alert")).toBeVisible();
  await expect(cancelled.locator(".lucide-ban")).toBeVisible();
});

async function createConversation(page: import("@playwright/test").Page): Promise<string> {
  await page.getByRole("button", { name: "New Chat", exact: true }).click();
  await expect(page).toHaveURL(/\/chats\/[0-9a-f-]+$/);
  const conversationId = page.url().split("/").pop();
  expect(conversationId).toBeTruthy();
  return conversationId as string;
}

/** Avoid real provider lookups while exercising chat CRUD flows. */
async function mockIdleChatContextSummary(page: import("@playwright/test").Page): Promise<void> {
  await page.route("**/api/chats/*/context-summary**", async (route) => {
    await route.fulfill({
      json: {
        used: 0,
        limit: 16_385,
        breakdown: {
          system: 0,
          agents_md: 0,
          workflows: 0,
          user_rules: 0,
          history: 0,
          attachment: 0,
        },
      },
    });
  });
}

test("creates a conversation and renames it", async ({ page }) => {
  const renamedTitle = `Renamed Chat ${Date.now()}`;

  await mockIdleChatContextSummary(page);
  await page.goto("/chats");
  await expect(page.getByText("Ask to run a workflow")).toBeVisible();

  const conversationId = await createConversation(page);
  const item = page.getByTestId(`chat-list-item-${conversationId}`);
  await expect(item).toBeVisible();

  // Settle after New Chat so credential/model bootstrap re-renders finish
  // before rename. focusInputWhenReady also refuses to steal from other inputs,
  // but waiting here avoids entering edit mode during the remount window.
  await expect(page.getByTestId("chat-credential-selector")).toBeVisible();
  await expect(page.getByPlaceholder("Type a message...")).toBeVisible();
  await expect(
    page.getByTestId("chat-model-selector").getByPlaceholder("Loading..."),
  ).toHaveCount(0);

  const renameResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/chats/${conversationId}`) &&
      response.request().method() === "PUT" &&
      response.ok(),
  );
  await item.hover();
  await item.getByTitle("Rename").click();
  const renameInput = item.locator("input");
  await expect(renameInput).toBeVisible();
  await renameInput.fill(renamedTitle);
  await renameInput.press("Enter");
  await renameResponsePromise;
  await expect(item).toContainText(renamedTitle);

  // The rename is server-persisted and survives a reload.
  await page.reload();
  await expect(page.getByTestId(`chat-list-item-${conversationId}`)).toContainText(renamedTitle);
});

test("creates and deletes a conversation", async ({ page }) => {
  await mockIdleChatContextSummary(page);
  await page.goto("/chats");
  await expect(page.getByText("Ask to run a workflow")).toBeVisible();

  const conversationId = await createConversation(page);
  const item = page.getByTestId(`chat-list-item-${conversationId}`);
  await expect(item).toBeVisible();

  const deleteResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/chats/${conversationId}`) &&
      response.request().method() === "DELETE" &&
      response.status() === 204,
  );
  await item.hover();
  await item.getByTitle("Delete").click();
  await item.getByTitle("Confirm delete").click();
  await deleteResponsePromise;
  await expect(page).toHaveURL(/\/chats$/);
  await expect(page.getByTestId(`chat-list-item-${conversationId}`)).toHaveCount(0);
});

test("filters chat credentials and models with searchable selectors", async ({ page }) => {
  const conversationId = "11111111-1111-4111-8111-111111111112";
  const openAiCredentialId = "22222222-2222-4222-8222-222222222223";
  const cerebrasCredentialId = "22222222-2222-4222-8222-222222222224";
  const now = new Date().toISOString();

  await page.route("**/api/workflows", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({
      json: [
        {
          id: openAiCredentialId,
          name: "OpenAI Main",
          type: "openai",
          masked_value: "sk-...",
          header_key: null,
          created_at: now,
        },
        {
          id: cerebrasCredentialId,
          name: "Cerebras Chat",
          type: "openai",
          masked_value: "csk-...",
          header_key: null,
          created_at: now,
        },
      ],
    });
  });
  await page.route(`**/api/credentials/${openAiCredentialId}/models`, async (route) => {
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
  await page.route(`**/api/credentials/${cerebrasCredentialId}/models`, async (route) => {
    await route.fulfill({
      json: [
        {
          id: "gemma-4-31b",
          name: "Gemma 4 31B",
          is_reasoning: false,
          supports_batch: false,
          batch_support_reason: null,
          context_window: 32768,
        },
        {
          id: "gpt-oss-120b",
          name: "GPT OSS 120B",
          is_reasoning: false,
          supports_batch: false,
          batch_support_reason: null,
          context_window: 131072,
        },
        {
          id: "zai-glm-4.7",
          name: "ZAI GLM 4.7",
          is_reasoning: false,
          supports_batch: false,
          batch_support_reason: null,
          context_window: 65536,
        },
      ],
    });
  });
  await page.route("**/api/chats/quick-prompts", async (route) => {
    await route.fulfill({ json: { prompts: [] } });
  });
  await page.route(`**/api/chats/${conversationId}/context-summary**`, async (route) => {
    await route.fulfill({
      json: {
        used: 0,
        limit: 1000,
        breakdown: {
          system: 0,
          agents_md: 0,
          workflows: 0,
          user_rules: 0,
          history: 0,
          attachment: 0,
        },
      },
    });
  });
  await page.route(`**/api/chats/${conversationId}/read`, async (route) => {
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/chats", async (route) => {
    await route.fulfill({
      json: {
        conversations: [
          {
            id: conversationId,
            title: "Selector Chat",
            is_pinned: false,
            is_running: false,
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
        title: "Selector Chat",
        is_pinned: false,
        is_running: false,
        has_unread: false,
        last_credential_id: openAiCredentialId,
        last_model: "gpt-4o",
        created_at: now,
        updated_at: now,
        messages: [],
        queued_messages: [],
      },
    });
  });

  await page.goto(`/chats/${conversationId}`);

  const credentialField = page.getByTestId("chat-credential-selector");
  const modelField = page.getByTestId("chat-model-selector");
  await expect(credentialField.getByRole("combobox")).toHaveValue("OpenAI Main");
  await expect(modelField.getByRole("combobox")).toHaveValue("GPT-4o");

  await selectSearchableOption(page, credentialField, "Cerebras Chat");
  await expect(credentialField.getByRole("combobox")).toHaveValue("Cerebras Chat");
  await expect(modelField.getByRole("combobox")).toHaveValue("ZAI GLM 4.7");

  await selectSearchableOption(page, modelField, "GPT OSS 120B");
  await expect(modelField.getByRole("combobox")).toHaveValue("GPT OSS 120B");
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

test("edits an earlier message and resends it from that point", async ({ page }) => {
  const conversationId = "66666666-6666-4666-8666-666666666666";
  const credentialId = "22222222-2222-4222-8222-222222222222";
  const firstQuestionId = "77777777-7777-4777-8777-777777777771";
  const secondQuestionId = "77777777-7777-4777-8777-777777777773";
  const editedQuestionId = "77777777-7777-4777-8777-777777777775";
  const now = new Date().toISOString();
  const message = (id: string, role: "user" | "assistant", content: string) => ({
    id,
    role,
    content,
    created_at: now,
    tool_calls: null,
  });
  let messages = [
    message(firstQuestionId, "user", "First question"),
    message("77777777-7777-4777-8777-777777777772", "assistant", "First answer"),
    message(secondQuestionId, "user", "Second question"),
    message("77777777-7777-4777-8777-777777777774", "assistant", "Second answer"),
  ];
  let sentBody: Record<string, unknown> | null = null;

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
    await route.fulfill({ json: { prompts: [] } });
  });
  await page.route(`**/api/chats/${conversationId}/context-summary**`, async (route) => {
    await route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  await page.route(`**/api/chats/${conversationId}/read`, async (route) => {
    await route.fulfill({ status: 204 });
  });
  await page.route(`**/api/chats/${conversationId}/stream`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        'data: {"type":"content","text":"Fresh answer","message_id":"77777777-7777-4777-8777-777777777776"}\n\n' +
        'data: {"type":"done"}\n\n',
    });
  });
  await page.route(`**/api/chats/${conversationId}/messages`, async (route) => {
    sentBody = (await route.request().postDataJSON()) as Record<string, unknown>;
    const edited = message(editedQuestionId, "user", String(sentBody.content));
    messages = [...messages.slice(0, 2), edited];
    await route.fulfill({
      status: 202,
      json: { conversation_id: conversationId, status: "started", user_message: edited },
    });
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
            title: "Edit Chat",
            is_pinned: false,
            is_running: false,
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
        title: "Edit Chat",
        is_pinned: false,
        is_running: false,
        has_unread: false,
        last_credential_id: credentialId,
        last_model: "gpt-4o",
        created_at: now,
        updated_at: now,
        messages,
        queued_messages: [],
      },
    });
  });

  await page.goto(`/chats/${conversationId}`);
  const thread = page.locator("#chat-messages-scroll");
  await expect(thread.getByText("Second answer")).toBeVisible();
  await expect(page.getByPlaceholder("Type a message...")).toBeEnabled();

  const secondQuestion = thread.locator(".group\\/message", { hasText: "Second question" });
  const editButton = secondQuestion.getByRole("button", { name: "Edit message" });
  await expect(editButton).toHaveCSS("opacity", "0");
  // The actions sit outside the question's bubble, so a short question keeps a short bubble.
  const bubbleBox = await secondQuestion.boundingBox();
  const actionsBox = await secondQuestion.getByTestId("chat-message-actions").boundingBox();
  expect(bubbleBox).not.toBeNull();
  expect(actionsBox).not.toBeNull();
  expect(actionsBox!.x + actionsBox!.width).toBeLessThanOrEqual(bubbleBox!.x + 1);
  await secondQuestion.hover();
  await expect(editButton).not.toHaveCSS("opacity", "0");
  await editButton.click();

  const editor = page.getByTestId("chat-message-editor");
  const editBox = editor.getByRole("textbox", { name: "Edit message" });
  await expect(editBox).toHaveValue("Second question");
  await editBox.fill("Second question, rephrased");
  await editor.getByRole("button", { name: "Save and send" }).click();

  await expect(thread.getByText("Fresh answer")).toBeVisible();
  await expect(thread.getByText("Second question, rephrased")).toBeVisible();
  await expect(thread.getByText("Second answer")).toHaveCount(0);
  await expect(thread.getByText("Second question", { exact: true })).toHaveCount(0);
  await expect(thread.getByText("First answer")).toBeVisible();
  await expect(editor).toHaveCount(0);
  expect(sentBody).toMatchObject({
    content: "Second question, rephrased",
    credential_id: credentialId,
    model: "gpt-4o",
    edit_message_id: secondQuestionId,
  });
});

test("cancels a message edit without sending", async ({ page }) => {
  const conversationId = "88888888-8888-4888-8888-888888888888";
  const credentialId = "22222222-2222-4222-8222-222222222222";
  const now = new Date().toISOString();
  let sends = 0;

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
      json: [{ id: "gpt-4o", name: "GPT-4o", is_reasoning: false, supports_batch: false, batch_support_reason: null, context_window: 128000 }],
    });
  });
  await page.route("**/api/chats/quick-prompts", async (route) => {
    await route.fulfill({ json: { prompts: [] } });
  });
  await page.route(`**/api/chats/${conversationId}/context-summary**`, async (route) => {
    await route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  await page.route(`**/api/chats/${conversationId}/read`, async (route) => {
    await route.fulfill({ status: 204 });
  });
  await page.route(`**/api/chats/${conversationId}/messages`, async (route) => {
    sends += 1;
    await route.fulfill({ status: 500, json: { detail: "unexpected" } });
  });
  await page.route("**/api/chats", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({ json: { conversations: [] } });
  });
  await page.route(`**/api/chats/${conversationId}`, async (route) => {
    await route.fulfill({
      json: {
        id: conversationId,
        title: "Cancel Chat",
        is_pinned: false,
        is_running: false,
        has_unread: false,
        last_credential_id: credentialId,
        last_model: "gpt-4o",
        created_at: now,
        updated_at: now,
        messages: [
          { id: "99999999-9999-4999-8999-999999999991", role: "user", content: "Keep me", created_at: now, tool_calls: null },
          { id: "99999999-9999-4999-8999-999999999992", role: "assistant", content: "Kept answer", created_at: now, tool_calls: null },
        ],
        queued_messages: [],
      },
    });
  });

  await page.goto(`/chats/${conversationId}`);
  const thread = page.locator("#chat-messages-scroll");
  const question = thread.locator(".group\\/message", { hasText: "Keep me" });
  await expect(thread.getByText("Kept answer")).toBeVisible();
  await question.hover();
  await question.getByRole("button", { name: "Edit message" }).click();
  const editBox = page.getByTestId("chat-message-editor").getByRole("textbox", { name: "Edit message" });
  await editBox.fill("Changed my mind");
  await editBox.press("Escape");

  await expect(page.getByTestId("chat-message-editor")).toHaveCount(0);
  await expect(thread.getByText("Keep me", { exact: true })).toBeVisible();
  await expect(thread.getByText("Kept answer")).toBeVisible();
  expect(sends).toBe(0);
});
