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

test("renders long model options outside the properties panel without clipping", async ({ page }) => {
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: `Long model credential ${Date.now()}`,
      type: "openai",
      config: { api_key: "sk-long-model-e2e" },
    },
  });
  await expectOk(credentialResponse);
  const credential = await credentialResponse.json() as { id: string };
  const workflow = await createWorkflow(page, `Long model popup ${Date.now()}`, [
    {
      id: "llm-long-model",
      type: "llm",
      position: { x: 200, y: 150 },
      data: {
        label: "llm",
        credentialId: credential.id,
        model: "",
        systemInstruction: "",
        userMessage: "",
        outputType: "text",
      },
    },
  ]);
  const longModel =
    "A very long provider model name with deployment region version reasoning profile and an extended descriptive suffix that must remain fully readable";

  await page.route(`**/api/credentials/${credential.id}/models`, async (route) => {
    await route.fulfill({
      json: [{ id: "long-model-id", name: longModel }],
    });
  });

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="llm-long-model"]').click();

    await page.getByPlaceholder("Select model...").click();
    const option = page.getByRole("option", { name: longModel });
    await expect(option).toBeVisible();
    expect(await option.evaluate((element) => element.closest(".properties-panel") === null)).toBe(
      true,
    );

    const panelBox = await page.locator(".properties-panel").boundingBox();
    const optionBox = await option.boundingBox();
    expect(panelBox).not.toBeNull();
    expect(optionBox).not.toBeNull();
    expect(optionBox!.width).toBeGreaterThan(panelBox!.width);
    expect(optionBox!.x).toBeGreaterThanOrEqual(0);
    expect(optionBox!.x + optionBox!.width).toBeLessThanOrEqual(
      await page.evaluate(() => window.innerWidth),
    );
    expect(
      await option.locator("span").last().evaluate(
        (element) => window.getComputedStyle(element).textOverflow,
      ),
    ).not.toBe("ellipsis");
    await option.click();
    await expect(page.getByPlaceholder("Select model...")).toHaveValue(longModel);
  } finally {
    await deleteWorkflow(page, workflow.id);
    await deleteCredential(page, credential.id);
  }
});

test("filters AI Assistant and Analyzer credentials and models", async ({ page }) => {
  const openAiCredentialId = "22222222-2222-4222-8222-222222222227";
  const cerebrasCredentialId = "22222222-2222-4222-8222-222222222228";
  const workflow = await createWorkflow(page, `Canvas AI selectors ${Date.now()}`);
  const now = new Date().toISOString();

  await page.route("**/api/credentials/llm", async (route) => {
    await route.fulfill({
      json: [
        {
          id: openAiCredentialId,
          name: "OpenAI Canvas",
          type: "openai",
          masked_value: "sk-...",
          header_key: null,
          created_at: now,
        },
        {
          id: cerebrasCredentialId,
          name: "Cerebras Canvas",
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
          id: "gpt-4o-canvas",
          name: "GPT-4o Canvas",
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
          id: "llama-canvas",
          name: "Llama Canvas",
          is_reasoning: false,
          supports_batch: false,
          batch_support_reason: null,
          context_window: 32768,
        },
        {
          id: "zai-glm-canvas",
          name: "ZAI GLM Canvas",
          is_reasoning: false,
          supports_batch: false,
          batch_support_reason: null,
          context_window: 65536,
        },
      ],
    });
  });

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByTitle("AI Assistant").click();

    const assistantCredential = page.getByTestId("ai-assistant-credential-selector");
    const assistantModel = page.getByTestId("ai-assistant-model-selector");
    await expect(assistantCredential.getByRole("combobox")).toHaveValue("OpenAI Canvas");
    await expect(assistantModel.getByRole("combobox")).toHaveValue("GPT-4o Canvas");
    await selectSearchableOption(page, assistantCredential, "Cerebras Canvas");
    await expect(assistantModel.getByRole("combobox")).toHaveValue("ZAI GLM Canvas");
    await selectSearchableOption(page, assistantModel, "Llama Canvas");
    await expect(assistantModel.getByRole("combobox")).toHaveValue("Llama Canvas");

    await page.getByRole("button", { name: "Analyze", exact: true }).click();
    const analyzerCredential = page.getByTestId("ai-analyzer-credential-selector");
    const analyzerModel = page.getByTestId("ai-analyzer-model-selector");
    await expect(analyzerCredential.getByRole("combobox")).toHaveValue("OpenAI Canvas");
    await expect(analyzerModel.getByRole("combobox")).toHaveValue("GPT-4o Canvas");
    await selectSearchableOption(page, analyzerCredential, "Cerebras Canvas");
    await expect(analyzerModel.getByRole("combobox")).toHaveValue("ZAI GLM Canvas");
    await selectSearchableOption(page, analyzerModel, "Llama Canvas");
    await expect(analyzerModel.getByRole("combobox")).toHaveValue("Llama Canvas");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
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

test("keeps precise folder and subfolder drop feedback active while dragging", async ({ page }) => {
  const workflow = await createWorkflow(page, `Folder drag workflow ${Date.now()}`);
  const parentResponse = await page.request.post("/api/folders", {
    data: { name: `Drag target ${Date.now()}` },
  });
  await expectOk(parentResponse);
  const parent = await parentResponse.json() as { id: string; name: string };
  const childResponse = await page.request.post("/api/folders", {
    data: { name: "Nested target", parent_id: parent.id },
  });
  await expectOk(childResponse);
  const child = await childResponse.json() as { id: string };

  try {
    await page.goto("/");

    const workflowCard = page.getByTestId(`workflow-card-${workflow.id}`);
    const parentZone = page.getByTestId(`workflow-folder-drop-zone-${parent.id}`);
    const childZone = page.getByTestId(`workflow-folder-drop-zone-${child.id}`);
    const dataTransfer = await page.evaluateHandle(() => new DataTransfer());

    await workflowCard.dispatchEvent("dragstart", { dataTransfer });
    await expect(workflowCard).toHaveClass(/workflow-card--dragging/);
    await expect(page.getByTestId("workflow-drag-ghost")).toHaveCount(1);

    await parentZone.dispatchEvent("dragover", { dataTransfer });
    const parentPlaceholder = page.getByTestId(
      `workflow-folder-drop-placeholder-${parent.id}`,
    );
    await expect(parentZone).toHaveAttribute("data-drop-active", "true");
    await expect(parentPlaceholder).toHaveAttribute("data-drop-valid", "true");
    await expect(parentPlaceholder).toContainText("Move to Folder");
    await expect(parentPlaceholder).toContainText(parent.name);
    await expect(childZone).toBeVisible({ timeout: 1_500 });

    // Moving between children and a scroll-style dragleave with no related target must not
    // clear the lane that is still under the pointer.
    await parentZone.evaluate((zone) => {
      const internalTarget = zone.querySelector<HTMLElement>("[data-testid^='workflow-folder-header-']");
      zone.dispatchEvent(new DragEvent("dragleave", {
        bubbles: true,
        relatedTarget: internalTarget,
      }));
      zone.dispatchEvent(new DragEvent("dragleave", { bubbles: true }));
    });
    await expect(parentZone).toHaveAttribute("data-drop-active", "true");
    await expect(parentPlaceholder).toBeVisible();

    await childZone.dispatchEvent("dragover", { dataTransfer });
    const childPlaceholder = page.getByTestId(
      `workflow-folder-drop-placeholder-${child.id}`,
    );
    await expect(parentZone).toHaveAttribute("data-drop-active", "false");
    await expect(childZone).toHaveAttribute("data-drop-active", "true");
    await expect(childPlaceholder).toContainText("Move to Subfolder");
    await expect(childPlaceholder).toContainText(`${parent.name} / Nested target`);

    const moveResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname === `/api/folders/${child.id}/workflows/${workflow.id}`,
    );
    await childZone.dispatchEvent("drop", { dataTransfer });
    await expectOk(await moveResponsePromise);

    await expect(page.getByTestId("workflow-drag-ghost")).toHaveCount(0);
    await expect(childZone.getByTestId(`workflow-card-${workflow.id}`)).toBeVisible();

    const movedCard = childZone.getByTestId(`workflow-card-${workflow.id}`);
    const sameFolderTransfer = await page.evaluateHandle(() => new DataTransfer());
    await movedCard.dispatchEvent("dragstart", { dataTransfer: sameFolderTransfer });
    await childZone.dispatchEvent("dragover", { dataTransfer: sameFolderTransfer });
    await expect(childPlaceholder).toHaveAttribute("data-drop-valid", "false");
    await expect(childPlaceholder).toContainText("Already in Subfolder");
    await movedCard.dispatchEvent("dragend", { dataTransfer: sameFolderTransfer });
  } finally {
    await deleteWorkflow(page, workflow.id);
    await expectOk(await page.request.delete(`/api/folders/${parent.id}`));
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
  // Scope to the output <pre> — the Execution Highlights popup also renders this
  // node's output as a preview span, so an unscoped getByText is ambiguous.
  await expect(
    page.locator("pre").filter({ hasText: /"httpStatusCode":\s*400/ }),
  ).toBeVisible();

  await deleteWorkflow(page, workflow.id);
});

test("shows execution highlights after a workflow run", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Highlights Workflow ${Date.now()}`,
    [
      {
        id: "set-highlight",
        type: "set",
        position: { x: 120, y: 120 },
        data: {
          label: "Build Highlight",
          mappings: [{ key: "message", value: "Canvas highlight smoke" }],
          highlight: true,
        },
      },
      {
        id: "output-final",
        type: "output",
        position: { x: 460, y: 120 },
        data: { label: "Final Output", message: "$input.message" },
      },
    ],
    [
      {
        id: "edge-highlight-output",
        source: "set-highlight",
        target: "output-final",
        sourceHandle: "output",
        targetHandle: "input",
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByRole("button", { name: "Run Workflow" }).click();

    const highlightsPanel = page.getByTestId("execution-highlights-panel");

    await expect(highlightsPanel).toBeVisible();
    const highlightedNodeRow = highlightsPanel.getByRole("button", { name: /Build Highlight/ });
    const finalOutputRow = highlightsPanel.getByRole("button", { name: /Final Output/ });
    await expect(highlightedNodeRow).toContainText("Canvas highlight smoke");
    await expect(finalOutputRow).toContainText("Canvas highlight smoke");

    await highlightsPanel.getByPlaceholder("Search highlights...").fill("smoke");
    await expect(highlightsPanel.locator("mark").filter({ hasText: "smoke" }).first()).toBeVisible();

    await highlightsPanel.getByPlaceholder("Search highlights...").fill("not-present");
    await expect(highlightsPanel.getByText("No matching highlights.")).toBeVisible();

    await highlightsPanel.getByLabel("Clear search").click();
    await highlightsPanel.getByLabel("Close highlights").click();
    await expect(page.getByTestId("execution-highlights-open")).toBeVisible();
    await page.getByTestId("execution-highlights-open").click();
    await expect(highlightsPanel).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("keeps execution highlights collapsed by default on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });

  const workflow = await createWorkflow(
    page,
    `Mobile Highlights ${Date.now()}`,
    [
      {
        id: "set-highlight",
        type: "set",
        position: { x: 120, y: 120 },
        data: {
          label: "Build Highlight",
          mappings: [{ key: "message", value: "Mobile highlight smoke" }],
          highlight: true,
        },
      },
      {
        id: "output-final",
        type: "output",
        position: { x: 460, y: 120 },
        data: { label: "Final Output", message: "$input.message" },
      },
    ],
    [
      {
        id: "edge-highlight-output",
        source: "set-highlight",
        target: "output-final",
        sourceHandle: "output",
        targetHandle: "input",
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.getByTestId("workflow-title")).toBeVisible();
    await expect(page.getByText("Build Highlight")).toBeVisible();

    // On mobile the properties panel starts closed and the Run label is icon-only
    // below `sm`, so drive the run via the editor shortcut instead.
    await page.keyboard.press("ControlOrMeta+Enter");

    // The shortcut opens the properties panel; close it so the canvas chip is
    // unobstructed on a narrow viewport.
    await expect(page.locator(".properties-panel")).toBeVisible();
    await page.locator("button.panel-toggle-right").click();
    await expect(page.locator(".properties-panel")).toBeHidden();

    await expect(page.getByTestId("execution-highlights-open")).toBeVisible();
    await expect(page.getByTestId("execution-highlights-panel")).toBeHidden();

    await page.getByTestId("execution-highlights-open").click();
    await expect(page.getByTestId("execution-highlights-panel")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
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

test("configures a Sentry node operation with searchable select", async ({ page }) => {
  const credentialResponse = await page.request.post("/api/credentials", {
    data: {
      name: `E2E Sentry ${Date.now()}`,
      type: "sentry",
      config: { api_token: "sntrys_e2e_test" },
    },
  });
  await expectOk(credentialResponse);
  const credential = (await credentialResponse.json()) as { id: string };
  const workflow = await createWorkflow(page, `Sentry Workflow ${Date.now()}`, [
    {
      id: "sentry-node",
      type: "sentry",
      position: { x: 200, y: 150 },
      data: {
        label: "sentry",
        credentialId: credential.id,
        sentryOperation: "listIssues",
      },
    },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const sentryNode = page.locator('.vue-flow__node[data-id="sentry-node"]');
    await expect(sentryNode).toBeVisible();
    await page.getByRole("button", { name: "Properties" }).click();
    await sentryNode.click();

    const operationField = page.getByTestId("sentry-operation-field");
    await expect(operationField.getByRole("combobox")).toHaveValue("List Issues");
    await expect(page.getByText("Organization Slug", { exact: true })).toBeVisible();
    await expect(page.getByText("Stats Period", { exact: true })).toBeVisible();
    await expect(page.getByText("Limit", { exact: true })).toBeVisible();

    await operationField.getByRole("combobox").click();
    await expect(page.getByText("Issue", { exact: true })).toBeVisible();
    await expect(page.getByText("Event", { exact: true })).toBeVisible();
    await expect(page.getByText("Release", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");

    await selectSearchableOption(page, operationField, "Get Issue");
    await expect(operationField.getByRole("combobox")).toHaveValue("Get Issue");
    await expect(page.getByText("Issue ID", { exact: true })).toBeVisible();
    await expect(page.getByText("Organization Slug", { exact: true })).toBeVisible();

    await selectSearchableOption(page, operationField, "Update Issue");
    await expect(operationField.getByRole("combobox")).toHaveValue("Update Issue");
    await expect(page.getByText("Issue ID", { exact: true })).toBeVisible();
    await expect(page.getByText("Status", { exact: true })).toBeVisible();
    await expect(page.getByText("Assigned To", { exact: true })).toBeVisible();

    await selectSearchableOption(page, operationField, "Delete Issue");
    await expect(operationField.getByRole("combobox")).toHaveValue("Delete Issue");
    await expect(page.getByText("Issue ID", { exact: true })).toBeVisible();
    await expect(page.getByText("Organization Slug", { exact: true })).toBeVisible();
    await expect(page.getByText("Payload JSON", { exact: true })).toBeHidden();

    await selectSearchableOption(page, operationField, "Update Project");
    await expect(operationField.getByRole("combobox")).toHaveValue("Update Project");
    await expect(page.getByText("Project Slug", { exact: true })).toBeVisible();
    await expect(page.getByText("Payload JSON", { exact: true })).toBeVisible();

    await selectSearchableOption(page, operationField, "Delete Release");
    await expect(operationField.getByRole("combobox")).toHaveValue("Delete Release");
    await expect(page.getByText("Release Version", { exact: true })).toBeVisible();
    await expect(page.getByText("Payload JSON", { exact: true })).toBeHidden();

    await selectSearchableOption(page, operationField, "Update Team");
    await expect(operationField.getByRole("combobox")).toHaveValue("Update Team");
    await expect(page.getByText("Team Slug", { exact: true })).toBeVisible();
    await expect(page.getByText("Payload JSON", { exact: true })).toBeVisible();
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
