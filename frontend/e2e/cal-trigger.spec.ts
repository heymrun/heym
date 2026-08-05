import { createHmac } from "node:crypto";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

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

interface FakeCalApi {
  baseUrl: string;
  server: Server;
  createBodies: Record<string, unknown>[];
  authorizationHeaders: string[];
}

async function startFakeCalApi(): Promise<FakeCalApi> {
  const createBodies: Record<string, unknown>[] = [];
  const authorizationHeaders: string[] = [];
  const server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      authorizationHeaders.push(request.headers.authorization || "");
      if (request.method === "POST" && request.url === "/v2/webhooks") {
        createBodies.push(JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>);
        response.writeHead(201, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { id: "managed-hook-1" } }));
        return;
      }
      if (request.method === "DELETE" && request.url === "/v2/webhooks/managed-hook-1") {
        response.writeHead(204);
        response.end();
        return;
      }
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ message: "Not found" }));
    });
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address() as AddressInfo;
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    server,
    createBodies,
    authorizationHeaders,
  };
}

async function stopFakeCalApi(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => error ? reject(error) : resolve());
  });
}

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

test("managed Cal.com API mode creates a webhook and accepts its signed delivery", async ({ page }) => {
  const fakeCal = await startFakeCalApi();
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: `Managed Cal API ${Date.now()}`,
      type: "cal_api",
      config: { api_key: "managed-api-key", base_url: fakeCal.baseUrl },
    },
  });
  await expectOk(credentialResponse);
  const credential = (await credentialResponse.json()) as { id: string };
  const workflow = await createWorkflow(
    page,
    `Managed Cal Trigger ${Date.now()}`,
    [
      {
        id: "managed-cal-trigger",
        type: "calTrigger",
        position: { x: 120, y: 160 },
        data: {
          label: "calEvent",
          setupMode: "managed",
          credentialId: "",
          calApiCredentialId: "",
          events: ["BOOKING_CREATED"],
          payloadVersion: "2021-10-20",
          active: true,
        },
      },
      {
        id: "managed-output",
        type: "output",
        position: { x: 460, y: 160 },
        data: { label: "result", message: "$calEvent.payload.title" },
      },
    ],
    [{ id: "managed-cal-to-output", source: "managed-cal-trigger", target: "managed-output" }],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator('.vue-flow__node[data-id="managed-cal-trigger"]');
    await expect(node).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await node.click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByText("Cal.com API Credential", { exact: true })).toBeVisible();
    await panel.getByRole("combobox").nth(1).selectOption(credential.id);
    await panel.getByRole("checkbox", { name: "BOOKING_CANCELLED" }).check();
    await panel.getByRole("checkbox", { name: "AFTER_HOSTS_CAL_VIDEO_NO_SHOW" }).check();
    await expect(panel.getByText("No-show evaluation delay")).toBeVisible();
    await panel.getByRole("button", { name: "Save & Sync" }).click();
    await expect(panel.getByText("active", { exact: true })).toBeVisible({ timeout: 15_000 });

    expect(fakeCal.authorizationHeaders[0]).toBe("Bearer managed-api-key");
    expect(fakeCal.createBodies).toHaveLength(1);
    const createBody = fakeCal.createBodies[0];
    expect(createBody.triggers).toEqual([
      "BOOKING_CREATED",
      "BOOKING_CANCELLED",
      "AFTER_HOSTS_CAL_VIDEO_NO_SHOW",
    ]);
    expect(createBody.payloadTemplate).toBe("");
    expect(createBody.time).toBe(5);
    expect(createBody.timeUnit).toBe("MINUTE");
    expect(createBody.subscriberUrl).toMatch(
      new RegExp(`/api/cal/webhook/${workflow.id}/managed-cal-trigger$`),
    );
    expect(typeof createBody.secret).toBe("string");

    const eventBody = JSON.stringify({
      triggerEvent: "BOOKING_CREATED",
      idempotencyKey: `managed-cal-${Date.now()}`,
      payload: { title: "Managed Cal webhook reached Heym" },
    });
    const signature = createHmac("sha256", createBody.secret as string)
      .update(eventBody)
      .digest("hex");
    const webhookResponse = await page.request.post(
      `/api/cal/webhook/${workflow.id}/managed-cal-trigger`,
      {
        data: eventBody,
        headers: {
          "content-type": "application/json",
          "x-cal-signature-256": signature,
        },
      },
    );
    await expectOk(webhookResponse);

    await expect.poll(async () => {
      const historyResponse = await page.request.get(
        `/api/workflows/${workflow.id}/history?trigger_source=Cal.com`,
      );
      await expectOk(historyResponse);
      const payload = (await historyResponse.json()) as { items: { status: string }[] };
      return payload.items[0]?.status;
    }, { timeout: 30_000 }).toBe("success");
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
    await stopFakeCalApi(fakeCal.server);
  }
});
