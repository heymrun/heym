import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("fileUploadTrigger workflow returns a single-use upload curl on canvas run", async ({
  page,
}) => {
  const workflow = await createWorkflow(
    page,
    "File Upload Trigger E2E",
    [
      {
        id: "n1",
        type: "fileUploadTrigger",
        position: { x: 120, y: 120 },
        data: { label: "audio", ttlMinutes: 30, maxSizeMb: 50, allowedTypes: "audio/*" },
      },
    ],
    [],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);

    await page.getByRole("button", { name: "Run Workflow" }).click();

    // The debug panel surfaces the minted upload link instead of running the body.
    await expect(page.getByText("File upload required")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("pre", { hasText: "/api/file-intake/u/" })).toBeVisible();
    await expect(page.getByText("Max size: 50 MB")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("canvas advances to the run result after the file is uploaded", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    "File Upload Trigger Advance E2E",
    [
      {
        id: "n1",
        type: "fileUploadTrigger",
        position: { x: 120, y: 120 },
        data: { label: "audio", ttlMinutes: 30, maxSizeMb: 50, allowedTypes: "audio/*" },
      },
      {
        id: "n2",
        type: "output",
        position: { x: 420, y: 120 },
        data: { label: "Result", value: "Got $audio.file.name" },
      },
    ],
    [{ id: "e1", source: "n1", target: "n2" }],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(2);

    await page.getByRole("button", { name: "Run Workflow" }).click();
    await expect(page.getByText("File upload required")).toBeVisible({ timeout: 30_000 });

    // Read the minted upload URL out of the rendered curl command.
    const curl = await page.locator("pre", { hasText: "/api/file-intake/u/" }).innerText();
    const match = curl.match(/'(https?:\/\/[^']*\/api\/file-intake\/u\/[^']+)'/);
    expect(match).not.toBeNull();
    const uploadUrl = match![1];

    // Upload a file out of band, like an agent running the returned curl.
    const uploadResponse = await page.request.post(uploadUrl, {
      multipart: {
        file: {
          name: "clip.mp3",
          mimeType: "audio/mpeg",
          buffer: Buffer.from("fake-audio"),
        },
      },
    });
    expect(uploadResponse.ok()).toBeTruthy();

    // The canvas polls the slot and advances to show the upload-triggered run.
    await expect(page.getByText("File upload required")).toBeHidden({ timeout: 20_000 });
    await expect(page.getByText("clip.mp3").first()).toBeVisible({ timeout: 20_000 });
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("fileUploadTrigger node renders on the canvas with its label", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    "File Upload Trigger Config E2E",
    [
      {
        id: "n1",
        type: "fileUploadTrigger",
        position: { x: 120, y: 120 },
        data: { label: "audio", ttlMinutes: 60, maxSizeMb: 100, allowedTypes: "" },
      },
    ],
    [],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator(".vue-flow__node").first();
    await expect(node).toBeVisible({ timeout: 15_000 });
    await expect(node).toContainText("audio");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
