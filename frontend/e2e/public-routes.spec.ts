import { expect, test } from "@playwright/test";

import {
  createWorkflow,
  deleteWorkflow,
  expectOk,
  prepareAuthenticatedPage,
  selectSearchableOption,
} from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("opens an enabled Chat Portal", async ({ page }) => {
  const workflow = await createWorkflow(page, `Portal Workflow ${Date.now()}`);
  const slug = `e2e-portal-${Date.now()}`;
  const portalResponse = await page.request.put(`/api/workflows/${workflow.id}/portal`, {
    data: {
      portal_enabled: true,
      portal_slug: slug,
      portal_stream_enabled: false,
    },
  });
  await expectOk(portalResponse);

  await page.goto(`/chat/${slug}`);
  await expect(page.getByRole("heading", { name: workflow.name })).toBeVisible();
  await expect(page.getByText("Portal not found")).toHaveCount(0);

  await deleteWorkflow(page, workflow.id);
});

test("renders HITL Review and submits acceptance with a mocked API", {
  tag: "@smoke",
}, async ({ page }) => {
  const token = "e2e-hitl-token";
  await page.route(`**/api/hitl/${token}**`, async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        json: { request_id: "request-1", status: "resolved" },
      });
      return;
    }
    await route.fulfill({
      json: {
        request_id: "request-1",
        workflow_name: "Approval Workflow",
        agent_label: "Reviewer Agent",
        summary: "Please approve this generated plan.",
        original_draft_text: "# Proposed plan\n\nShip the tested change.",
        status: "pending",
        decision: null,
        edited_text: null,
        refusal_reason: null,
        resolved_output: {},
        expires_at: new Date(Date.now() + 60_000).toISOString(),
        resolved_at: null,
      },
    });
  });

  await page.goto(`/review/${token}`);
  await expect(page.getByRole("heading", { name: "Approval Workflow" })).toBeVisible();
  await expect(page.getByText("Please approve this generated plan.")).toBeVisible();
  await page.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByText(/Accepted successfully/)).toBeVisible();
});

test("browses documentation articles", async ({ page }) => {
  await page.goto("/docs/getting-started/introduction");
  await expect(page.getByRole("heading", { name: "Introduction", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Quick Start", exact: true }).first().click();

  await expect(page).toHaveURL(/\/docs\/getting-started\/quick-start$/);
  await expect(page.getByRole("heading", { name: "Quick Start", exact: true })).toBeVisible();

  await page.goto("/docs/nodes/sentry-node");
  await expect(page.getByRole("heading", { name: "Sentry Node", exact: true })).toBeVisible();
  await expect(page.getByText("Delete an issue:", { exact: true })).toBeVisible();
});

test("filters Chat with Docs credentials and models with searchable selectors", async ({ page }) => {
  const openAiCredentialId = "22222222-2222-4222-8222-222222222225";
  const cerebrasCredentialId = "22222222-2222-4222-8222-222222222226";
  const now = new Date().toISOString();

  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({
      json: [
        {
          id: openAiCredentialId,
          name: "OpenAI Docs",
          type: "openai",
          masked_value: "sk-...",
          header_key: null,
          created_at: now,
        },
        {
          id: cerebrasCredentialId,
          name: "Cerebras Docs",
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

  await page.goto("/docs/getting-started/introduction");
  await page.getByRole("button", { name: "Chat with Docs" }).click();
  await expect(page.getByRole("heading", { name: "Chat with Docs" })).toBeVisible();

  const credentialField = page.getByTestId("docs-chat-credential-selector");
  const modelField = page.getByTestId("docs-chat-model-selector");
  await expect(credentialField.getByRole("combobox")).toHaveValue("OpenAI Docs");
  await expect(modelField.getByRole("combobox")).toHaveValue("GPT-4o");

  await selectSearchableOption(page, credentialField, "Cerebras Docs");
  await expect(credentialField.getByRole("combobox")).toHaveValue("Cerebras Docs");
  await expect(modelField.getByRole("combobox")).toHaveValue("ZAI GLM 4.7");

  await selectSearchableOption(page, modelField, "GPT OSS 120B");
  await expect(modelField.getByRole("combobox")).toHaveValue("GPT OSS 120B");
});
