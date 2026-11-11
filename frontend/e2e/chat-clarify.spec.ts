import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test("every chat question accepts Other even without allowOther or with it disabled", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  const conversationId = "11111111-1111-4111-8111-111111111121";
  const credentialId = "22222222-2222-4222-8222-222222222221";
  const now = new Date().toISOString();
  const questions = [
    {
      id: "smtp",
      text: "Which SMTP credential should send the notification email?",
      type: "single",
      options: ["enterprise", "support"],
    },
    {
      id: "outputs",
      text: "Which outputs are needed?",
      type: "multi",
      options: ["Email", "Slack"],
      allowOther: false,
    },
    { id: "note", text: "What should the message say?", type: "text", allowOther: true },
    {
      id: "subject",
      text: "Which email subject should I use?",
      type: "single",
      options: ["Notification"],
      allowOther: false,
      optional: true,
    },
  ];
  const conversation = {
    id: conversationId,
    title: "Clarification choices",
    is_pinned: false,
    is_running: false,
    has_unread: false,
    last_credential_id: credentialId,
    last_model: "gpt-4o",
    created_at: now,
    updated_at: now,
  };
  const messages = [{
    id: "33333333-3333-4333-8333-333333333331",
    role: "assistant",
    content: ["Please clarify the workflow.", "```heym-clarify", JSON.stringify({ questions }), "```"].join("\n"),
    created_at: now,
  }];
  let submitted = "";

  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({ json: [{
      id: credentialId, name: "Mock OpenAI", type: "openai", created_at: now,
    }] });
  });
  await page.route(`**/api/credentials/${credentialId}/models`, async (route) => {
    await route.fulfill({ json: [{ id: "gpt-4o", name: "GPT-4o", is_reasoning: false }] });
  });
  await page.route(/\/api\/chats(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/chats") {
      await route.fulfill({ json: { conversations: [conversation] } });
    } else if (path === `/api/chats/${conversationId}`) {
      await route.fulfill({ json: { ...conversation, messages, queued_messages: [] } });
    } else if (path.endsWith("/messages")) {
      const body = route.request().postDataJSON() as { content: string };
      submitted = body.content;
      const userMessage = {
        id: "44444444-4444-4444-8444-444444444441",
        role: "user",
        content: submitted,
        created_at: now,
      };
      messages.push(userMessage);
      await route.fulfill({
        status: 202,
        json: { conversation_id: conversationId, status: "started", user_message: userMessage },
      });
    } else if (path.endsWith("/stream")) {
      await route.fulfill({
        headers: { "content-type": "text/event-stream" },
        body: 'data: {"type":"done"}\n\n',
      });
    } else if (path.endsWith("/read")) {
      await route.fulfill({ status: 204 });
    } else if (path.endsWith("/context-summary")) {
      await route.fulfill({ json: { used: 0, limit: 128000, breakdown: {} } });
    } else {
      await route.fulfill({ json: { prompts: [] } });
    }
  });

  await page.goto(`/chats/${conversationId}`);
  await expect(page.getByTestId("chat-model-selector").getByRole("combobox")).toHaveValue("GPT-4o");
  const card = page.locator(".clarify-card");
  const submit = card.getByRole("button", { name: "Submit answers" });
  await expect(card.getByRole("textbox")).toHaveCount(1);
  await expect(card.getByRole("button", { name: "Other", exact: true })).toHaveCount(3);
  await expect(submit).toBeDisabled();

  const smtpQuestion = card.getByRole("group", { name: questions[0].text });
  const smtpOther = smtpQuestion.getByRole("button", { name: "Other", exact: true });
  const smtp = card.getByRole("textbox", { name: questions[0].text });
  await expect(smtp).toHaveCount(0);
  const enterprise = card.getByRole("button", { name: "enterprise", exact: true });
  await enterprise.click();
  await expect(enterprise).toHaveClass(/active/);
  await smtpOther.click();
  await expect(smtp).toBeFocused();
  await expect(smtpOther).toHaveAttribute("aria-expanded", "true");
  await expect(smtp).toHaveAttribute("placeholder", "Other…");
  await smtp.fill("Use a different sender");
  await expect(enterprise).not.toHaveClass(/active/);
  // Picking a chip closes Other; opening it again starts with an empty answer.
  await enterprise.click();
  await expect(smtp).toHaveCount(0);
  await expect(smtpOther).toHaveAttribute("aria-expanded", "false");
  await smtpOther.click();
  await expect(smtp).toHaveValue("");
  await smtp.fill("Use the billing SMTP credential");

  const email = card.getByRole("button", { name: "Email", exact: true });
  await email.click();
  await card.getByRole("group", { name: questions[1].text })
    .getByRole("button", { name: "Other", exact: true }).click();
  await card.getByRole("textbox", { name: questions[1].text }).fill("SMS");
  await expect(email).toHaveClass(/active/);
  const note = card.getByRole("textbox", { name: questions[2].text });
  await expect(note).toHaveAttribute("placeholder", "Your answer");
  await note.fill("   ");
  await expect(submit).toBeDisabled();
  await note.fill("Notify when finished");
  const optionalOther = card.getByRole("group", { name: questions[3].text })
    .getByRole("button", { name: "Other", exact: true });
  await optionalOther.click();
  const subject = card.getByRole("textbox", { name: questions[3].text });
  await expect(subject).toHaveAttribute("placeholder", "Other… (optional)");
  await subject.fill("Custom subject");
  await optionalOther.click();
  await expect(subject).toHaveCount(0);
  await expect(submit).toBeEnabled();
  await submit.click();

  await expect.poll(() => submitted).toBe([
    "[Plan answers]",
    `- ${questions[0].text} → Other: "Use the billing SMTP credential"`,
    `- ${questions[1].text} → Email, Other: "SMS"`,
    `- ${questions[2].text} → Other: "Notify when finished"`,
    `- ${questions[3].text} → (skipped)`,
  ].join("\n"));
  for (const question of questions.slice(0, 3)) {
    await expect(card.getByRole("textbox", { name: question.text })).toBeDisabled();
  }
  await expect(optionalOther).toBeDisabled();
});
