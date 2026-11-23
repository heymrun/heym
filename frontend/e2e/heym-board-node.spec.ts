import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test("configures board operations and exposes their IDs as expressions and agent tool inputs", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  const workflow = await createWorkflow(page, "Heym board operations", [
    { id: "boardReader", type: "heym", position: { x: 0, y: 0 }, data: { label: "boardReader", heymOperation: "getBoard" } },
    { id: "agent", type: "agent", position: { x: 400, y: 0 }, data: { label: "agent" } },
  ], [
    { id: "tool", source: "boardReader", target: "agent", sourceHandle: "tool-output", targetHandle: "tool-input" },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator('.vue-flow__node[data-id="boardReader"]');
    await expect(node).toBeVisible();
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await node.click();
    const panel = page.locator(".properties-panel");
    const operation = panel.getByTestId("heym-operation").locator("select");

    for (const [value, field] of [
      ["getBoard", "heymBoardId"],
      ["getBoardColumn", "heymBoardColumnId"],
      ["getBoardCardId", "heymBoardCardId"],
    ]) {
      await operation.selectOption(value);
      const fieldInput = panel.getByTestId(`heym-field-${field}`);
      await fieldInput.getByTitle("Click to let agent fill this at runtime").click();
      await expect(fieldInput.getByText("Agent will provide this at runtime.")).toBeVisible();
      await fieldInput.getByTitle("Agent fills this — click to use fixed value").click();
      await expect(panel.getByPlaceholder("Select a workflow...")).toHaveCount(0);
    }

    await node.dblclick();
    await expect(page.getByRole("heading", { name: "boardReader – Card ID", exact: true })).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("selects board, column and card by name and keeps the ID field editable", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  const boardId = "89d3dfa9-ba11-48e7-900a-c8319e4d711a";
  const columnId = "f6382309-a0e0-4e45-a2b1-7fcb93e0304a";
  const cardId = "8bcd214b-e8cb-4cb0-a075-6702b67f78d6";
  await page.route("**/api/boards", (route) => route.fulfill({ json: [
    { id: boardId, name: "Product board" },
    { id: "b5947c25-e6df-4c83-a1c0-fc15ceca2280", name: "Support board" },
  ] }));
  await page.route(`**/api/boards/${boardId}`, (route) => route.fulfill({ json: {
    id: boardId,
    columns: [{ id: columnId, name: "Planning" }],
    cards: [{ id: cardId, title: "Review onboarding", column_id: columnId }],
  } }));
  const workflow = await createWorkflow(page, "Heym board pickers", [
    { id: "boardReader", type: "heym", position: { x: 0, y: 0 }, data: { label: "boardReader", heymOperation: "getBoard" } },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    const node = page.locator('.vue-flow__node[data-id="boardReader"]');
    await expect(node).toBeVisible();
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await node.click();
    const panel = page.locator(".properties-panel");
    const operation = panel.getByTestId("heym-operation").locator("select");

    for (const target of [
      { operation: "getBoard", placeholder: "Select a board…", field: "heymBoardId", label: "Product board", id: boardId, expression: "$input.board_id" },
      { operation: "getBoardColumn", placeholder: "Select a column…", field: "heymBoardColumnId", label: "Planning", id: columnId, expression: "$board.columns[0].id" },
      { operation: "getBoardCardId", placeholder: "Select a card…", field: "heymBoardCardId", label: "Review onboarding", id: cardId, expression: "$column.cards[0].id" },
    ]) {
      await operation.selectOption(target.operation);
      await panel.getByPlaceholder(target.placeholder, { exact: true }).click();
      await page.getByRole("option").filter({ hasText: target.label }).click();
      const input = panel.getByTestId(`heym-field-${target.field}`).locator("textarea");
      await expect(input).toHaveValue(target.id);
      await input.fill(target.expression);
      await expect(input).toHaveValue(target.expression);
    }
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
