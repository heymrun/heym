import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

async function openDecisionNode(
  page: import("@playwright/test").Page,
  name: string,
  data: Record<string, unknown>,
): Promise<string> {
  const workflow = await createWorkflow(page, `${name} ${Date.now()}`, [
    {
      id: "decision-node",
      type: "decision",
      position: { x: 120, y: 160 },
      data: {
        label: "decision",
        credentialId: "",
        model: "jev-1.14.0",
        state: "",
        customBodyEnabled: false,
        customBody: "",
        requestTimeoutSeconds: 60,
        ...data,
      },
    },
  ]);
  await page.goto(`/workflows/${workflow.id}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(1);
  await page.getByRole("button", { name: "Properties", exact: true }).click();
  await page.locator('.vue-flow__node[data-id="decision-node"]').click();
  return workflow.id;
}

test("turning on images seeds a photo row and adds more", async ({ page }) => {
  const workflowId = await openDecisionNode(page, "Decision Images", {
    imagesEnabled: false,
    images: [],
    questions: [{ id: "is_dog", type: "noul", instructions: "Is there a dog in `photo`?" }],
  });

  try {
    const editor = page.locator(".properties-panel").getByTestId("decision-images-editor");
    await expect(editor).toBeVisible();
    await expect(editor.getByTestId("decision-image-row")).toHaveCount(0);

    await editor.getByLabel("Send images").check();
    const rows = editor.getByTestId("decision-image-row");
    await expect(rows).toHaveCount(1);
    await expect(rows.first().getByLabel("Image name")).toHaveValue("photo");

    await editor.getByRole("button", { name: "Add image" }).click();
    await expect(rows).toHaveCount(2);

    await rows.nth(1).getByLabel("Image name").fill("2 bad");
    await expect(rows.nth(1)).toContainText("Use letters, digits and underscores");

    await rows.nth(1).getByRole("button", { name: "Remove image" }).click();
    await expect(rows).toHaveCount(1);
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("a box question shows instructions without criteria", async ({ page }) => {
  const workflowId = await openDecisionNode(page, "Decision Box", {
    imagesEnabled: true,
    images: [{ name: "photo", source: "$input.body.imageUrl" }],
    questions: [{ id: "dog", type: "box", instructions: "the dog in `photo`" }],
  });

  try {
    const panel = page.locator(".properties-panel");
    await expect(panel).toContainText("jev-1.14.0 or jev-preview");
    await expect(panel.getByText("Levels (lowest first)")).toHaveCount(0);
    await expect(panel.getByText("Yes means")).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Option", exact: true })).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});
