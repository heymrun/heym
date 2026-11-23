import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test("Send Chat Message shows its switches and a QUESTION output only while a question can be answered", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  const workflow = await createWorkflow(page, "Heym chat message", [
    { id: "chat", type: "heym", position: { x: 0, y: 0 }, data: { label: "chat", heymOperation: "sendChatMessage", heymChatMessage: "Summarize today" } },
    { id: "reply", type: "set", position: { x: 400, y: -120 }, data: { label: "reply" } },
    { id: "ask", type: "set", position: { x: 400, y: 120 }, data: { label: "ask" } },
  ], [
    { id: "out", source: "chat", target: "reply", sourceHandle: "output", targetHandle: "input" },
    { id: "q", source: "chat", target: "ask", sourceHandle: "question", targetHandle: "input" },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator('.vue-flow__node[data-id="chat"]');
    await expect(node).toBeVisible();
    await expect(node.getByText("QUESTION", { exact: true })).toBeVisible();
    await expect(node.locator('.vue-flow__handle[data-handleid="question"]')).toHaveCount(1);
    await expect(page.locator(".vue-flow__edge")).toHaveCount(2);

    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await node.click();
    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("heym-field-heymChatMessage").locator("textarea")).toHaveValue("Summarize today");
    await expect(panel.getByPlaceholder("Select a workflow...")).toHaveCount(0);

    const noHistory = panel.locator("#heym-heymChatNoHistory");
    const continueChat = panel.locator("#heym-heymChatContinue");
    const fireAndForget = panel.locator("#heym-heymChatFireAndForget");
    for (const toggle of [noHistory, continueChat, fireAndForget]) {
      await expect(toggle).not.toBeChecked();
    }
    await expect(panel.getByTestId("heym-field-heymChatConversationId")).toHaveCount(0);

    await continueChat.check();
    await expect(noHistory).toBeDisabled();
    const conversationId = panel.getByTestId("heym-field-heymChatConversationId").locator("textarea");
    await conversationId.fill("$previous.conversation_id");
    await expect(conversationId).toHaveValue("$previous.conversation_id");

    await node.dblclick();
    await expect(page.getByRole("heading", { name: "chat – Message", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");

    await continueChat.uncheck();
    await expect(noHistory).toBeEnabled();

    // Without history a question could not be answered later: no QUESTION output.
    await noHistory.check();
    await expect(continueChat).toBeDisabled();
    await expect(node.getByText("QUESTION", { exact: true })).toHaveCount(0);
    await expect(node.locator('.vue-flow__handle[data-handleid="question"]')).toHaveCount(0);
    await expect(page.locator(".vue-flow__edge")).toHaveCount(1);
    await noHistory.uncheck();
    await expect(node.getByText("QUESTION", { exact: true })).toBeVisible();

    // Without waiting the reply never reaches the node: no QUESTION output either.
    await fireAndForget.check();
    await expect(node.getByText("QUESTION", { exact: true })).toHaveCount(0);
    await fireAndForget.uncheck();
    await expect(node.getByText("QUESTION", { exact: true })).toBeVisible();

    await panel.getByTestId("heym-operation").locator("select").selectOption("listWorkflows");
    await expect(node.getByText("QUESTION", { exact: true })).toHaveCount(0);
    await expect(node.locator('.vue-flow__handle[data-handleid="question"]')).toHaveCount(0);
    await expect(page.locator(".vue-flow__edge")).toHaveCount(1);
    await expect(panel.getByTestId("heym-field-heymChatMessage")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
