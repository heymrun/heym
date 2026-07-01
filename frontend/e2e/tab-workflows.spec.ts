import { expect, test } from "@playwright/test";

import {
  acceptNextDialog,
  createWorkflow,
  deleteWorkflow,
  deleteCredential,
  expectOk,
  prepareAuthenticatedPage,
  selectSearchableOption,
} from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("creates, edits, saves, runs, reloads, and deletes a workflow", async ({ page }) => {
  const workflowName = `E2E Workflow ${Date.now()}`;
  const renamedWorkflow = `${workflowName} Renamed`;

  await page.goto("/");
  await expect(
    page.getByRole("main").getByRole("heading", { name: "Workflows" }),
  ).toBeVisible();

  await page.getByTestId("new-workflow-button").click();
  await expect(page.getByRole("heading", { name: "Create New Workflow" })).toBeVisible();
  const createForm = page.locator("form").filter({
    has: page.getByLabel("Description (optional)"),
  });
  await createForm.getByLabel("Name", { exact: true }).fill(workflowName);
  await createForm.getByLabel("Description (optional)").fill("Created by Playwright");
  await createForm.getByRole("button", { name: "Create Workflow" }).click();

  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]+$/);
  const workflowId = page.url().split("/").pop();
  expect(workflowId).toBeTruthy();
  await expect(page.getByTestId("workflow-title")).toHaveText(workflowName);

  await page.getByTestId("workflow-title").dispatchEvent("mousedown");
  const titleInput = page.locator("[data-heym-inline-edit] input").first();
  await titleInput.fill(renamedWorkflow);
  await titleInput.press("Enter");
  await expect(page.getByTestId("workflow-title")).toHaveText(renamedWorkflow);

  await page.getByTestId("node-palette-consoleLog").dblclick();
  await expect(page.locator(".vue-flow__node")).toHaveCount(1);

  const saveButton = page.getByTestId("save-workflow-button");
  await expect(saveButton).toBeEnabled();
  await saveButton.click();
  await expect(saveButton).toBeDisabled();

  await page.getByRole("button", { name: "Run Workflow" }).click();
  await expect(page.getByText("Last Executed Node")).toBeVisible();
  await expect(page.getByText("success", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("workflow-title")).toHaveText(renamedWorkflow);
  await expect(page.locator(".vue-flow__node")).toHaveCount(1);

  await page.goto("/");
  await expect(page).toHaveURL("/");

  const workflowCard = page.getByTestId(`workflow-card-${workflowId}`);
  await expect(workflowCard).toBeVisible();
  await acceptNextDialog(
    page,
    () => page.getByTestId(`workflow-delete-${workflowId}`).click(),
    "Are you sure you want to delete this workflow?",
  );
  await expect(workflowCard).toBeHidden();
  await expect(page.getByText("Workflow deleted successfully")).toBeVisible();
});

test("creates a folder and filters workflows with search", async ({ page }) => {
  const workflowName = `Searchable Workflow ${Date.now()}`;
  const folderName = `E2E Folder ${Date.now()}`;
  const workflow = await createWorkflow(page, workflowName);
  let folderId: string | undefined;

  try {
    await page.goto("/");
    await page.getByRole("button", { name: "New Folder" }).first().click();
    await page.getByLabel("Folder Name").fill(folderName);
    const folderResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/folders",
    );
    await page.getByRole("button", { name: "Create", exact: true }).click();
    const folderResponse = await folderResponsePromise;
    const folder = await folderResponse.json() as { id: string };
    folderId = folder.id;

    await expect(page.getByText(folderName, { exact: true })).toBeVisible();
    await page.getByPlaceholder("Search workflows").fill(workflowName);
    await expect(page.getByTestId(`workflow-card-${workflow.id}`)).toBeVisible();
    await page.getByPlaceholder("Search workflows").fill("definitely-not-present");
    await expect(page.getByText("No workflows found")).toBeVisible();
  } finally {
    if (folderId) {
      await expectOk(await page.request.delete(`/api/folders/${folderId}`));
    }
    await deleteWorkflow(page, workflow.id);
  }
});

test("imports and exports a workflow JSON file", async ({ page }) => {
  const importedName = `Imported Workflow ${Date.now()}`;
  const importPayload = {
    name: importedName,
    nodes: [
      {
        id: "console-1",
        type: "consoleLog",
        position: { x: 120, y: 100 },
        data: { label: "consoleLog", logMessage: "$input" },
      },
    ],
    edges: [],
  };

  await page.goto("/");
  const dataTransfer = await page.evaluateHandle((payload) => {
    const transfer = new DataTransfer();
    transfer.items.add(
      new File([JSON.stringify(payload)], "imported-workflow.json", {
        type: "application/json",
      }),
    );
    return transfer;
  }, importPayload);
  await page.getByTestId("workflow-import-dropzone").dispatchEvent("drop", {
    dataTransfer,
  });

  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]+$/);
  await expect(page.getByTestId("workflow-title")).toHaveText(importedName);
  await expect(page.locator(".vue-flow__node")).toHaveCount(1);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.json$/);

  const workflowId = page.url().split("/").pop();
  if (workflowId) {
    await deleteWorkflow(page, workflowId);
  }
});

test("renders multiple connected nodes and persists the edge", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Connected Workflow ${Date.now()}`,
    [
      {
        id: "console-source",
        type: "consoleLog",
        position: { x: 100, y: 100 },
        data: { label: "consoleLog", logMessage: "$input" },
      },
      {
        id: "output-target",
        type: "output",
        position: { x: 500, y: 100 },
        data: { label: "output", output: "$input" },
      },
    ],
    [
      {
        id: "edge-console-output",
        source: "console-source",
        target: "output-target",
        sourceHandle: "output",
        targetHandle: "input",
      },
    ],
  );

  await page.goto(`/workflows/${workflow.id}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(2);
  await expect(page.locator(".vue-flow__edge-path")).toHaveCount(1);
  await page.reload();
  await expect(page.locator(".vue-flow__edge-path")).toHaveCount(1);

  await deleteWorkflow(page, workflow.id);
});

test("shows the workflow name without overflow on small screens", async ({ page }) => {
  const longName = `Small Screen Workflow ${Date.now()} With A Very Long Name That Should Truncate`;
  const workflow = await createWorkflow(page, longName);

  try {
    // Emulate a small / narrow viewport where the header has little horizontal room.
    await page.setViewportSize({ width: 380, height: 720 });
    await page.goto(`/workflows/${workflow.id}`);

    const title = page.getByTestId("workflow-title");
    // The name must remain visible on small screens, not hidden away.
    await expect(title).toBeVisible();
    await expect(title).toHaveText(longName);

    // The title must stay within the viewport (truncated), never overflowing horizontally.
    const box = await title.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(380);

    // The element is actually clipped (truncated) rather than rendering its full width.
    const overflow = await title.evaluate(
      (el) => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }),
    );
    expect(overflow.scrollWidth).toBeGreaterThan(overflow.clientWidth);

    // Inline editing must not blow out the header width either.
    await title.dispatchEvent("mousedown");
    const titleInput = page.locator("[data-heym-inline-edit] input").first();
    await expect(titleInput).toBeVisible();
    const inputBox = await titleInput.boundingBox();
    expect(inputBox).not.toBeNull();
    expect(inputBox!.x + inputBox!.width).toBeLessThanOrEqual(380);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("collapses toolbar labels to icons when tight and keeps them when wide, with tooltips", async ({ page }) => {
  const workflow = await createWorkflow(page, `Toolbar Workflow ${Date.now()}`);
  const historyLabel = page
    .locator("header.editor-header span")
    .filter({ hasText: /^History$/ });

  try {
    // Wide screen that comfortably fits both the toolbar labels and the name:
    // the text labels stay visible (nothing changes for screens that fit).
    await page.setViewportSize({ width: 1700, height: 800 });
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.getByTestId("workflow-title")).toBeVisible();
    await expect(historyLabel).toBeVisible();

    // Tighter screen: the workflow name must still be fully visible, and the
    // toolbar text labels collapse to icons to make room.
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(page.getByTestId("workflow-title")).toBeVisible();
    await expect(historyLabel).toBeHidden();

    // Hovering an icon-only button reveals its name in a tooltip popup.
    const themeButton = page
      .locator("header.editor-header button")
      .filter({ has: page.locator("svg.lucide-sun, svg.lucide-moon") })
      .first();
    await themeButton.hover();
    await expect(page.getByRole("tooltip")).toContainText(/mode/i);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("shows a failed workflow execution", async ({ page }) => {
  const workflow = await createWorkflow(page, `Failing Workflow ${Date.now()}`);

  await page.goto(`/workflows/${workflow.id}`);
  await page.getByTestId("node-palette-throwError").dblclick();
  await page.getByTestId("save-workflow-button").click();
  await page.getByRole("button", { name: "Run Workflow" }).click();

  await expect(page.getByText("Last Executed Node")).toBeVisible();
  await expect(page.getByText("error", { exact: true })).toBeVisible();
  await expect(page.getByText(/"httpStatusCode":\s*400/)).toBeVisible();

  await deleteWorkflow(page, workflow.id);
});

test("adds and configures a Linear node", async ({ page }) => {
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: `E2E Linear ${Date.now()}`,
      type: "linear",
      config: { api_key: "lin_api_e2e_test" },
    },
  });
  await expectOk(credentialResponse);
  const credential = (await credentialResponse.json()) as { id: string };
  const workflow = await createWorkflow(page, `Linear Workflow ${Date.now()}`);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByTestId("node-palette-linear").dblclick();
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties" }).click();
    await page.locator(".vue-flow__node").click();

    await page
      .getByTestId("linear-credential-field")
      .locator("select")
      .selectOption(credential.id);
    await selectSearchableOption(page, page.getByTestId("linear-operation-field"), "Get Issue");
    await page
      .getByTestId("linear-issue-id-field")
      .locator("input")
      .fill("ENG-123");

    const saveButton = page.getByTestId("save-workflow-button");
    await expect(saveButton).toBeEnabled();
    await saveButton.click();
    await page.reload();

    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties" }).click();
    await page.locator(".vue-flow__node").click();
    await expect(
      page.getByTestId("linear-operation-field").getByRole("combobox"),
    ).toHaveValue("Get Issue");
    await expect(
      page.getByTestId("linear-issue-id-field").locator("input"),
    ).toHaveValue("ENG-123");

    await selectSearchableOption(
      page,
      page.getByTestId("linear-operation-field"),
      "List Workflow States",
    );
    await expect(page.getByTestId("linear-team-id-field")).toBeVisible();

    await selectSearchableOption(page, page.getByTestId("linear-operation-field"), "List Teams");
    await expect(page.getByTestId("linear-after-field")).toBeVisible();
    await page
      .getByTestId("linear-after-field")
      .locator("input")
      .fill("$previousLinear.pageInfo.endCursor");
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
  }
});

test("configures Linear listTeamMembers fields and persists after save", async ({ page }) => {
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: `E2E Linear Members ${Date.now()}`,
      type: "linear",
      config: { api_key: "lin_api_e2e_test" },
    },
  });
  await expectOk(credentialResponse);
  const credential = (await credentialResponse.json()) as { id: string };
  const workflow = await createWorkflow(page, `Linear Members Workflow ${Date.now()}`);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByTestId("node-palette-linear").dblclick();
    await page.getByRole("button", { name: "Properties" }).click();
    await page.locator(".vue-flow__node").click();

    await page
      .getByTestId("linear-credential-field")
      .locator("select")
      .selectOption(credential.id);
    await selectSearchableOption(
      page,
      page.getByTestId("linear-operation-field"),
      "List Team Members",
    );
    await expect(page.getByTestId("linear-team-id-field")).toBeVisible();
    await expect(page.getByTestId("linear-limit-field")).toBeVisible();
    await expect(page.getByTestId("linear-after-field")).toBeVisible();
    await page
      .getByTestId("linear-team-id-field")
      .locator("input")
      .fill("team-uuid-1");
    await page.getByTestId("linear-limit-field").locator("input").fill("25");
    await page
      .getByTestId("linear-after-field")
      .locator("input")
      .fill("cursor-members-1");

    await page.getByTestId("save-workflow-button").click();
    await page.reload();
    await page.getByRole("button", { name: "Properties" }).click();
    await page.locator(".vue-flow__node").click();

    await expect(
      page.getByTestId("linear-operation-field").getByRole("combobox"),
    ).toHaveValue("List Team Members");
    await expect(page.getByTestId("linear-team-id-field").locator("input")).toHaveValue(
      "team-uuid-1",
    );
    await expect(page.getByTestId("linear-limit-field").locator("input")).toHaveValue("25");
    await expect(page.getByTestId("linear-after-field").locator("input")).toHaveValue(
      "cursor-members-1",
    );
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
  }
});

test("configures Linear comment operations and persists update comment fields", async ({ page }) => {
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: `E2E Linear Comments ${Date.now()}`,
      type: "linear",
      config: { api_key: "lin_api_e2e_test" },
    },
  });
  await expectOk(credentialResponse);
  const credential = (await credentialResponse.json()) as { id: string };
  const workflow = await createWorkflow(page, `Linear Comments Workflow ${Date.now()}`);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByTestId("node-palette-linear").dblclick();
    await page.getByRole("button", { name: "Properties" }).click();
    await page.locator(".vue-flow__node").click();

    await page
      .getByTestId("linear-credential-field")
      .locator("select")
      .selectOption(credential.id);

    await selectSearchableOption(
      page,
      page.getByTestId("linear-operation-field"),
      "List Comments",
    );
    await expect(page.getByTestId("linear-issue-id-field")).toBeVisible();
    await expect(page.getByTestId("linear-limit-field")).toBeVisible();
    await expect(page.getByTestId("linear-after-field")).toBeVisible();
    await page
      .getByTestId("linear-issue-id-field")
      .locator("input")
      .fill("ENG-123");
    await page.getByTestId("linear-limit-field").locator("input").fill("20");
    await page
      .getByTestId("linear-after-field")
      .locator("input")
      .fill("$listComments.pageInfo.endCursor");

    await selectSearchableOption(
      page,
      page.getByTestId("linear-operation-field"),
      "Delete Comment",
    );
    await expect(page.getByTestId("linear-comment-id-field")).toBeVisible();
    await expect(page.getByTestId("linear-issue-id-field")).toBeHidden();

    await selectSearchableOption(
      page,
      page.getByTestId("linear-operation-field"),
      "Resolve Comment",
    );
    await expect(page.getByTestId("linear-comment-id-field")).toBeVisible();

    await selectSearchableOption(
      page,
      page.getByTestId("linear-operation-field"),
      "Unresolve Comment",
    );
    await expect(page.getByTestId("linear-comment-id-field")).toBeVisible();

    await selectSearchableOption(
      page,
      page.getByTestId("linear-operation-field"),
      "Update Comment",
    );
    await expect(page.getByTestId("linear-comment-id-field")).toBeVisible();
    await expect(page.getByTestId("linear-comment-body-field")).toBeVisible();
    await page
      .getByTestId("linear-comment-id-field")
      .locator("input")
      .fill("comment-uuid-1");
    await page
      .getByTestId("linear-comment-body-field")
      .locator("textarea")
      .fill("Updated from $input.text");

    await page.getByTestId("save-workflow-button").click();
    await page.reload();
    await page.getByRole("button", { name: "Properties" }).click();
    await page.locator(".vue-flow__node").click();

    await expect(
      page.getByTestId("linear-operation-field").getByRole("combobox"),
    ).toHaveValue("Update Comment");
    await expect(page.getByTestId("linear-comment-id-field").locator("input")).toHaveValue(
      "comment-uuid-1",
    );
    await expect(
      page.getByTestId("linear-comment-body-field").locator("textarea"),
    ).toHaveValue("Updated from $input.text");
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
  }
});
