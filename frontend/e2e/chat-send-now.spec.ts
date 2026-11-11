import { expect, test, type Page } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

const CONVERSATION_ID = "11111111-1111-4111-8111-111111111131";
const CREDENTIAL_ID = "22222222-2222-4222-8222-222222222231";
const SELECTED_ID = "33333333-3333-4333-8333-333333333331";
const PARTIAL_ID = "44444444-4444-4444-8444-444444444431";
const USER_ID = "55555555-5555-4555-8555-555555555531";

async function mockQueuedChat(page: Page, fail = false): Promise<string[]> {
  await prepareAuthenticatedPage(page);
  const sentIds: string[] = [];
  let sent = false;
  const now = new Date().toISOString();
  const conversation = {
    id: CONVERSATION_ID, title: "Send a queued follow-up", is_running: true,
    is_pinned: false, has_unread: false, created_at: now, updated_at: now,
    last_credential_id: CREDENTIAL_ID, last_model: "gpt-4o",
  };
  const queue = [
    {
      id: "66666666-6666-4666-8666-666666666631", content: "Older follow-up",
      credential_id: CREDENTIAL_ID, model: "gpt-4o", created_at: now, updated_at: now,
    },
    {
      id: SELECTED_ID, content: "Use the billing SMTP credential",
      credential_id: CREDENTIAL_ID, model: "gpt-4o", created_at: now, updated_at: now,
      attachment_names: ["notes.txt"],
    },
  ];
  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({ json: [{
      id: CREDENTIAL_ID, name: "Mock OpenAI", type: "openai", created_at: now,
    }] });
  });
  await page.route(`**/api/credentials/${CREDENTIAL_ID}/models`, async (route) => {
    await route.fulfill({ json: [{ id: "gpt-4o", name: "GPT-4o", is_reasoning: false }] });
  });
  await page.route(/\/api\/chats(?:[/?]|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/chats") {
      await route.fulfill({ json: { conversations: [conversation] } });
    } else if (path === `/api/chats/${CONVERSATION_ID}`) {
      await route.fulfill({ json: {
        ...conversation,
        messages: [{ id: USER_ID, role: "user", content: "Original request", created_at: now }],
        queued_messages: sent ? [queue[0]] : queue,
      } });
    } else if (path.endsWith("/send-now")) {
      sentIds.push(path.split("/").at(-2)!);
      sent = !fail;
      await route.fulfill(fail
        ? { status: 409, json: { detail: "Please try again shortly." } }
        : { status: 202, json: { conversation_id: CONVERSATION_ID, status: "started", queued_message: queue[1] } });
    } else if (path.endsWith("/stream")) {
      const events = [
        { type: "content", text: "Partial reply", message_id: PARTIAL_ID },
        { type: "tool_start", id: "tool-1", name: "lookup", label: "Looking up data", args: {}, message_id: PARTIAL_ID },
        ...(sent ? [
          { type: "assistant_done", message_id: PARTIAL_ID, cancelled: true },
          { type: "queued_message_started", queued_message_id: SELECTED_ID, user_message: {
            id: "77777777-7777-4777-8777-777777777731", role: "user",
            content: queue[1].content, created_at: now,
          } },
          { type: "content", text: "Using the requested sender now.", message_id: "88888888-8888-4888-8888-888888888831" },
          { type: "assistant_done", paused_for_clarification: true },
          { type: "done" },
        ] : []),
      ];
      await route.fulfill({
        headers: { "content-type": "text/event-stream" },
        body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""),
      });
    } else if (path.endsWith("/read")) {
      await route.fulfill({ status: 204 });
    } else if (path.endsWith("/context-summary")) {
      await route.fulfill({ json: { used: 0, limit: 128000, breakdown: {} } });
    } else {
      await route.fulfill({ json: { prompts: [] } });
    }
  });
  return sentIds;
}

for (const width of [1280, 390]) {
  test(`sends the selected follow-up now and keeps the other queue item at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const sentIds = await mockQueuedChat(page);
    await page.goto(`/chats/${CONVERSATION_ID}`);
    const rows = page.getByTestId("chat-queue-item");
    await expect(rows).toHaveCount(2);
    const selected = rows.filter({ hasText: "Use the billing SMTP credential" });
    await expect(selected.getByTitle("Edit queued message")).toBeVisible();
    await expect(selected.getByTitle("Delete queued message")).toBeVisible();
    const sendNow = selected.getByRole("button", { name: "Send now", exact: true });
    await expect(sendNow).toHaveText("");
    await expect(sendNow.locator("svg")).toBeVisible();
    await sendNow.click();

    const thread = page.locator("#chat-messages-scroll");
    await expect(thread.getByText("Using the requested sender now.", { exact: true })).toBeVisible();
    await expect(thread.getByText("Partial reply", { exact: true })).toBeVisible();
    await expect(thread.getByText("Use the billing SMTP credential", { exact: true })).toBeVisible();
    await expect(thread.getByText("notes.txt", { exact: true })).toBeVisible();
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("Older follow-up");
    expect(sentIds).toEqual([SELECTED_ID]);
    expect(await rows.first().evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(false);
  });
}

test("keeps queued messages and shows a retryable send-now error", async ({ page }) => {
  const sentIds = await mockQueuedChat(page, true);
  await page.goto(`/chats/${CONVERSATION_ID}`);
  const selected = page.getByTestId("chat-queue-item").filter({ hasText: "Use the billing SMTP credential" });
  await selected.getByRole("button", { name: "Send now", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Please try again shortly.");
  await expect(page.getByTestId("chat-queue-item")).toHaveCount(2);
  await expect(selected.getByRole("button", { name: "Send now", exact: true })).toBeEnabled();
  expect(sentIds).toEqual([SELECTED_ID]);
});
