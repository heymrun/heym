import { expect, test } from "@playwright/test";

import {
  createWorkflow,
  deleteCredential,
  deleteWorkflow,
  expectOk,
  prepareAuthenticatedPage,
} from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("IMAP Trigger saves Download attachments to Drive and lists its outputs", async ({ page }) => {
  // A selected credential keeps the workflow valid, so Save is not refused.
  const created = await page.request.post("/api/credentials", {
    data: {
      name: `E2E inbox ${Date.now()}`,
      type: "imap",
      config: {
        imap_host: "imap.example.com",
        imap_port: 993,
        imap_username: "invoices@example.com",
        imap_password: "not-a-real-password",
        imap_mailbox: "INBOX",
        imap_use_ssl: true,
      },
    },
  });
  await expectOk(created);
  const credential = (await created.json()) as { id: string };
  const workflow = await createWorkflow(page, `IMAP Trigger ${Date.now()}`, [
    {
      id: "imap-trigger",
      type: "imapTrigger",
      position: { x: 120, y: 160 },
      data: { label: "invoiceInbox", credentialId: credential.id, pollIntervalMinutes: 5 },
    },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="imap-trigger"]').click();

    const panel = page.locator(".properties-panel");
    const toggle = panel
      .getByTestId("imap-download-attachments-field")
      .getByLabel("Download attachments to Drive");
    await expect(toggle).not.toBeChecked();
    await expect(panel.getByTestId("imap-output-fields")).toContainText("$invoiceInbox.file_ids");
    await expect(panel.getByTestId("imap-output-fields")).toContainText(
      "$invoiceInbox.attachments",
    );

    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname === `/api/workflows/${workflow.id}`,
    );
    await toggle.check();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await saved;

    const stored = await page.request.get(`/api/workflows/${workflow.id}`);
    expect(stored.ok()).toBeTruthy();
    const body = (await stored.json()) as { nodes: { id: string; data: Record<string, unknown> }[] };
    const node = body.nodes.find((item) => item.id === "imap-trigger");
    expect(node?.data.imapDownloadAttachments).toBe(true);

    await page.reload();
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="imap-trigger"]').click();
    await expect(
      page
        .locator(".properties-panel")
        .getByTestId("imap-download-attachments-field")
        .getByLabel("Download attachments to Drive"),
    ).toBeChecked();
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
  }
});
