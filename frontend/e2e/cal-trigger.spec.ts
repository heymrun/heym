import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

import {
  createWorkflow,
  deleteCredential,
  deleteWorkflow,
  expectOk,
  prepareAuthenticatedPage,
  selectSearchableOption,
} from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("Cal.com Trigger renders its signed webhook configuration", async ({ page }) => {
  const credentialName = `Cal selector credential ${Date.now()}`;
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: credentialName,
      type: "cal_trigger",
      config: { webhook_secret: "cal-selector-secret-for-e2e" },
    },
  });
  await expectOk(credentialResponse);
  const credential = (await credentialResponse.json()) as { id: string };
  const workflow = await createWorkflow(
    page,
    `Cal.com Trigger ${Date.now()}`,
    [
      {
        id: "cal-trigger",
        type: "calTrigger",
        position: { x: 120, y: 160 },
        data: {
          label: "calEvent",
          credentialId: "",
        },
      },
    ],
    [],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator('.vue-flow__node[data-id="cal-trigger"]');
    await expect(node).toBeVisible({ timeout: 15_000 });
    await expect(node).toContainText("calEvent");

    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await node.click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByText("Webhook Secret Credential")).toBeVisible();
    const credentialSelect = panel.getByRole("combobox").nth(1);
    await expect(credentialSelect).toBeEnabled();
    await expect(credentialSelect.locator(`option[value="${credential.id}"]`)).toHaveText(
      `${credentialName} (cal_trigger)`,
    );
    await expect(panel.getByText("No credential set — Cal.com requests will be rejected")).toBeVisible();
    await expect(
      panel.getByText("Cal.com Cloud requires a publicly reachable HTTPS URL", { exact: false }),
    ).toBeVisible();
    await expect(panel.getByText("Available output fields")).toBeVisible();
    await expect(panel.locator('input[readonly]')).toHaveValue(
      new RegExp(`/api/cal/webhook/${workflow.id}/cal-trigger$`),
    );

    await credentialSelect.selectOption(credential.id);
    await expect(credentialSelect).toHaveValue(credential.id);
    await expect(
      panel.getByText("Must match the secret configured on the Cal.com webhook."),
    ).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
  }
});

test("signed Cal.com webhook executes once and rejects an invalid signature", async ({ page }) => {
  const secret = `cal-e2e-secret-${Date.now()}`;
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: `Cal.com E2E ${Date.now()}`,
      type: "cal_trigger",
      config: { webhook_secret: secret },
    },
  });
  await expectOk(credentialResponse);
  const credential = (await credentialResponse.json()) as { id: string };
  const workflow = await createWorkflow(
    page,
    `Cal.com Webhook E2E ${Date.now()}`,
    [
      {
        id: "cal-trigger",
        type: "calTrigger",
        position: { x: 120, y: 160 },
        data: { label: "calEvent", credentialId: credential.id, active: true },
      },
      {
        id: "output-result",
        type: "output",
        position: { x: 460, y: 160 },
        data: { label: "result", message: "$calEvent.payload.title" },
      },
    ],
    [{ id: "cal-to-output", source: "cal-trigger", target: "output-result" }],
  );

  try {
    const body = JSON.stringify({
      triggerEvent: "BOOKING_CREATED",
      createdAt: new Date().toISOString(),
      idempotencyKey: `cal-e2e-${Date.now()}`,
      payload: { title: "Cal webhook reached the workflow" },
    });
    const signature = createHmac("sha256", secret).update(body).digest("hex");
    const webhookUrl = `/api/cal/webhook/${workflow.id}/cal-trigger`;
    const response = await page.request.post(webhookUrl, {
      data: body,
      headers: {
        "content-type": "application/json",
        "x-cal-signature-256": signature,
      },
    });
    await expectOk(response);

    await expect
      .poll(
        async () => {
          const historyResponse = await page.request.get(
            `/api/workflows/${workflow.id}/history?trigger_source=Cal.com`,
          );
          await expectOk(historyResponse);
          return (await historyResponse.json()) as {
            items: { id: string; status: string }[];
          };
        },
        { timeout: 30_000 },
      )
      .toMatchObject({ items: [{ status: "success" }] });

    const historyResponse = await page.request.get(
      `/api/workflows/${workflow.id}/history?trigger_source=Cal.com`,
    );
    await expectOk(historyResponse);
    const historyPayload = (await historyResponse.json()) as { items: { id: string }[] };
    const detailResponse = await page.request.get(
      `/api/workflows/${workflow.id}/history/${historyPayload.items[0].id}`,
    );
    await expectOk(detailResponse);
    const detail = (await detailResponse.json()) as {
      inputs: Record<string, unknown>;
      outputs: Record<string, unknown>;
      trigger_source: string;
    };
    expect(detail.trigger_source).toBe("Cal.com");
    expect(JSON.stringify(detail.inputs)).toContain("BOOKING_CREATED");
    expect(JSON.stringify(detail.outputs)).toContain("Cal webhook reached the workflow");

    const duplicateResponse = await page.request.post(webhookUrl, {
      data: body,
      headers: {
        "content-type": "application/json",
        "x-cal-signature-256": signature,
      },
    });
    await expectOk(duplicateResponse);
    await expect
      .poll(async () => {
        const historyResponse = await page.request.get(
          `/api/workflows/${workflow.id}/history?trigger_source=Cal.com`,
        );
        await expectOk(historyResponse);
        const payload = (await historyResponse.json()) as { items: unknown[] };
        return payload.items.length;
      })
      .toBe(1);

    const invalidResponse = await page.request.post(webhookUrl, {
      data: body,
      headers: {
        "content-type": "application/json",
        "x-cal-signature-256": "invalid",
      },
    });
    expect(invalidResponse.status()).toBe(403);
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
  }
});

test("Cal.com API operations live on a separate action node", async ({ page }) => {
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: `Cal API Node ${Date.now()}`,
      type: "cal_api",
      config: { api_key: "cal-api-key", base_url: "https://api.cal.com" },
    },
  });
  await expectOk(credentialResponse);
  const credential = (await credentialResponse.json()) as { id: string };
  const workflow = await createWorkflow(
    page,
    `Cal API Node ${Date.now()}`,
    [
      {
        id: "cal-api-node",
        type: "cal",
        position: { x: 120, y: 160 },
        data: {
          label: "calApi",
          credentialId: "",
          calOperation: "listWebhooks",
          calWebhookId: "",
          calWebhook: "{}",
        },
      },
    ],
    [],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator('.vue-flow__node[data-id="cal-api-node"]');
    await expect(node).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await node.click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByText("Cal.com API Credential", { exact: true })).toBeVisible();
    await panel.getByRole("combobox").nth(1).selectOption(credential.id);
    const operationField = panel.getByTestId("cal-operation-field");
    await selectSearchableOption(page, operationField, "Update Webhook");
    await expect(panel.getByTestId("cal-webhook-id-field")).toBeVisible();
    await expect(panel.getByTestId("cal-webhook-data-field")).toBeVisible();

    await selectSearchableOption(page, operationField, "Delete Webhook");
    await expect(panel.getByTestId("cal-webhook-id-field")).toBeVisible();
    await expect(panel.getByTestId("cal-webhook-data-field")).toBeHidden();
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
  }
});
