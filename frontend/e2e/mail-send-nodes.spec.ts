import { expect, test, type Page } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

const GMAIL_ID = "11111111-1111-4111-8111-111111111111";
const OUTLOOK_ID = "22222222-2222-4222-8222-222222222222";

function credential(id: string, type: string, name: string, publicFields: Record<string, string | null>): object {
  return {
    id, name, type, masked_value: "connected", is_shared: false, shared_by: null,
    created_at: new Date().toISOString(), public_fields: publicFields,
  };
}

async function mockMailAccounts(page: Page): Promise<void> {
  await page.route("**/api/credentials/by-type/gmail", (route) => route.fulfill({
    json: [credential(GMAIL_ID, "gmail", "Team Gmail", {})],
  }));
  // Connected before Outlook Send: no Mail.Send yet.
  await page.route("**/api/credentials/by-type/outlook", (route) => route.fulfill({
    json: [credential(OUTLOOK_ID, "outlook", "Team Outlook", { tenant: "common", can_send: null })],
  }));
  await page.route(`**/api/gmail/${GMAIL_ID}/addresses`, (route) => route.fulfill({
    json: {
      addresses: [
        { email: "team@example.com", display_name: "Team", is_primary: true },
        { email: "support@example.com", display_name: "Support", is_primary: false },
      ],
    },
  }));
  await page.route(`**/api/outlook/${OUTLOOK_ID}/addresses`, (route) => route.fulfill({
    json: { addresses: [{ email: "team@contoso.com", is_primary: true }] },
  }));
}

test("Gmail Send and Outlook Send share Send Email's fields and add From", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await mockMailAccounts(page);
  const workflow = await createWorkflow(page, `Mail send ${Date.now()}`, [
    {
      id: "gmail", type: "gmailSend", position: { x: 120, y: 160 },
      data: { label: "Reply", credentialId: GMAIL_ID, fromAddress: "", to: "a@example.com", subject: "Hi", emailBody: "$input.text" },
    },
    {
      id: "outlook", type: "outlookSend", position: { x: 420, y: 160 },
      data: { label: "Notify", credentialId: OUTLOOK_ID, fromAddress: "", to: "b@example.com", subject: "Hi", emailBody: "$input.text" },
    },
  ]);
  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator('.vue-flow__node[data-id="gmail"]')).toBeVisible();
    await page.getByRole("button", { name: "Properties", exact: true }).click();

    await page.locator('.vue-flow__node[data-id="gmail"]').click();
    const panel = page.locator(".properties-panel");
    await expect(panel.getByText("Gmail Credential", { exact: true })).toBeVisible();
    for (const label of ["From", "To", "Cc", "Bcc", "Subject", "Body", "Attachments"]) {
      await expect(panel.getByText(label, { exact: true }).first()).toBeVisible();
    }
    const fromField = panel.getByTestId("mail-send-from-field");
    await fromField.getByRole("button", { name: "support@example.com", exact: true }).click();
    await expect(fromField.locator("textarea")).toHaveValue("support@example.com");
    await expect(panel.getByTestId("mail-send-reconnect-hint")).toHaveCount(0);

    await page.locator('.vue-flow__node[data-id="gmail"]').dblclick();
    await expect(page.getByRole("heading", { name: "Reply – From", exact: true })).toBeVisible();
    await expect(page.getByText("1 / 7", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");

    await page.locator('.vue-flow__node[data-id="outlook"]').click();
    await expect(panel.getByText("Outlook Credential", { exact: true })).toBeVisible();
    await expect(panel.getByTestId("mail-send-reconnect-hint")).toContainText("Mail.Send");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
