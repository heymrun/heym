import { expect, test } from "@playwright/test";

import {
  createWorkflow,
  deleteAllBoards,
  deleteWorkflow,
  prepareAuthenticatedPage,
} from "./support";

// Board tests share one account's board list and assert on its empty state.
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await deleteAllBoards(page);
});

test.afterEach(async ({ page }) => {
  await deleteAllBoards(page);
});

test("creates a board with default columns and adds a card", async ({ page }) => {
  await page.goto("/?tab=board");
  await expect(page.getByTestId("board-panel")).toBeVisible();

  await page.getByTestId("board-empty-create").click();
  await page.getByPlaceholder("Board name").fill("Launch board");
  await page.getByRole("button", { name: "Create board" }).click();

  for (const columnName of ["Backlog", "Planning", "To Do", "Waiting", "Development", "Done"]) {
    await expect(page.getByTestId(`board-column-${columnName}`)).toBeVisible();
  }

  const backlog = page.getByTestId("board-column-Backlog");
  await backlog.getByPlaceholder("Add a card").fill("Write launch email");
  await backlog.getByPlaceholder("Add a card").press("Enter");
  await expect(backlog.getByText("Write launch email")).toBeVisible();
});

test("reflects the selected board in the URL and deep-links to it", async ({ page }) => {
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await page.getByPlaceholder("Board name").fill("URL board");
  await page.getByRole("button", { name: "Create board" }).click();

  await expect(page.getByTestId("board-column-Backlog")).toBeVisible();
  await expect(page).toHaveURL(/[?&]board=[0-9a-f-]{36}/);
  const boardId = new URL(page.url()).searchParams.get("board");
  expect(boardId).toBeTruthy();

  // Deep-link: reloading the board URL opens the same board.
  await page.goto(`/?tab=board&board=${boardId}`);
  await expect(page.getByTestId("board-column-Backlog")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`board=${boardId}`));
});

test("closes the new board dialog on Escape", async ({ page }) => {
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await expect(page.getByPlaceholder("Board name")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByPlaceholder("Board name")).not.toBeVisible();
});

test("clones and deletes a card from the hover actions", async ({ page }) => {
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await page.getByPlaceholder("Board name").fill("Hover board");
  await page.getByRole("button", { name: "Create board" }).click();

  const backlog = page.getByTestId("board-column-Backlog");
  await backlog.getByPlaceholder("Add a card").fill("Draft brief");
  await backlog.getByPlaceholder("Add a card").press("Enter");
  await expect(backlog.getByText("Draft brief")).toHaveCount(1);

  // Clone -> two identical cards.
  const card = backlog.locator("[data-board-card]").first();
  await card.hover();
  await card.locator('[data-testid^="board-card-clone-"]').click();
  await expect(backlog.getByText("Draft brief")).toHaveCount(2);

  // Delete -> confirm dialog accepted -> back to one card.
  page.once("dialog", (dialog) => dialog.accept());
  const firstCard = backlog.locator("[data-board-card]").first();
  await firstCard.hover();
  await firstCard.locator('[data-testid^="board-card-delete-"]').click();
  await expect(backlog.getByText("Draft brief")).toHaveCount(1);
});

type ApiCard = { id: string; run_status: string };

test("runs a column workflow chain to completion when a card enters", async ({ page }) => {
  const wf = await createWorkflow(
    page,
    `Board WF ${Date.now()}`,
    [
      {
        id: "s1",
        type: "set",
        position: { x: 100, y: 100 },
        data: { label: "greet", mappings: [{ key: "text", value: "done" }] },
      },
      {
        id: "o1",
        type: "output",
        position: { x: 400, y: 100 },
        data: { label: "out", message: "$greet.text" },
      },
    ],
    [{ id: "e1", source: "s1", target: "o1" }],
  );

  try {
    const board = await (await page.request.post("/api/boards", { data: { name: "Chain board" } })).json();
    const state = await (await page.request.get(`/api/boards/${board.id}`)).json();
    const planning = state.columns.find((c: { name: string }) => c.name === "Planning");
    const backlog = state.columns.find((c: { name: string }) => c.name === "Backlog");

    await page.request.patch(`/api/boards/${board.id}/columns/${planning.id}`, {
      data: { workflow_ids: [wf.id] },
    });
    const card = await (
      await page.request.post(`/api/boards/${board.id}/cards`, {
        data: { title: "run me", column_id: backlog.id },
      })
    ).json();
    await page.request.post(`/api/boards/${board.id}/cards/${card.id}/move`, {
      data: { to_column_id: planning.id },
    });

    let status = "";
    for (let i = 0; i < 40; i += 1) {
      const s = await (await page.request.get(`/api/boards/${board.id}`)).json();
      status = (s.cards as ApiCard[]).find((c) => c.id === card.id)?.run_status ?? "";
      if (status === "success" || status === "failed") break;
      await page.waitForTimeout(500);
    }
    expect(status).toBe("success");

    const detail = await (await page.request.get(`/api/boards/${board.id}/cards/${card.id}`)).json();
    expect(detail.runs.length).toBeGreaterThanOrEqual(1);
    expect(detail.runs[0].status).toBe("success");
  } finally {
    await deleteAllBoards(page);
    await deleteWorkflow(page, wf.id);
  }
});

test("auto-advances a card through columns to the last one", async ({ page }) => {
  const wf = await createWorkflow(
    page,
    `Advance WF ${Date.now()}`,
    [
      {
        id: "s1",
        type: "set",
        position: { x: 100, y: 100 },
        data: { label: "greet", mappings: [{ key: "text", value: "ok" }] },
      },
      {
        id: "o1",
        type: "output",
        position: { x: 400, y: 100 },
        data: { label: "out", message: "$greet.text" },
      },
    ],
    [{ id: "e1", source: "s1", target: "o1" }],
  );

  try {
    const board = await (await page.request.post("/api/boards", { data: { name: "Flow" } })).json();
    const state = await (await page.request.get(`/api/boards/${board.id}`)).json();
    const col = (name: string) => state.columns.find((c: { name: string }) => c.name === name);
    // Chain the same workflow on Planning and To Do; the rest are empty.
    for (const name of ["Planning", "To Do"]) {
      await page.request.patch(`/api/boards/${board.id}/columns/${col(name).id}`, {
        data: { workflow_ids: [wf.id] },
      });
    }
    const card = await (
      await page.request.post(`/api/boards/${board.id}/cards`, {
        data: { title: "flow me", column_id: col("Backlog").id },
      })
    ).json();
    await page.request.post(`/api/boards/${board.id}/cards/${card.id}/move`, {
      data: { to_column_id: col("Planning").id },
    });

    let columnName = "";
    let status = "";
    for (let i = 0; i < 60; i += 1) {
      const s = await (await page.request.get(`/api/boards/${board.id}`)).json();
      const c = (s.cards as { id: string; column_id: string; run_status: string }[]).find(
        (x) => x.id === card.id,
      );
      const columns: { id: string; name: string }[] = s.columns;
      columnName = columns.find((x) => x.id === c?.column_id)?.name ?? "";
      status = c?.run_status ?? "";
      // Done is the last column and has no chain, so the card should end there, green.
      if (columnName === "Done" && status === "success") break;
      if (status === "failed") break;
      await page.waitForTimeout(500);
    }
    expect(status).toBe("success");
    expect(columnName).toBe("Done");
  } finally {
    await deleteAllBoards(page);
    await deleteWorkflow(page, wf.id);
  }
});

test("keeps flowing right when moved into a column that has no chain", async ({ page }) => {
  const wf = await createWorkflow(
    page,
    `Flow WF ${Date.now()}`,
    [
      {
        id: "s1",
        type: "set",
        position: { x: 100, y: 100 },
        data: { label: "greet", mappings: [{ key: "text", value: "ok" }] },
      },
      {
        id: "o1",
        type: "output",
        position: { x: 400, y: 100 },
        data: { label: "out", message: "$greet.text" },
      },
    ],
    [{ id: "e1", source: "s1", target: "o1" }],
  );

  try {
    const board = await (await page.request.post("/api/boards", { data: { name: "Flow2" } })).json();
    const state = await (await page.request.get(`/api/boards/${board.id}`)).json();
    const col = (name: string) => state.columns.find((c: { name: string }) => c.name === name);
    // Chain only on "To Do". Planning (the move target) is empty.
    await page.request.patch(`/api/boards/${board.id}/columns/${col("To Do").id}`, {
      data: { workflow_ids: [wf.id] },
    });
    const card = await (
      await page.request.post(`/api/boards/${board.id}/cards`, {
        data: { title: "flow me", column_id: col("Backlog").id },
      })
    ).json();
    // Forward move into the EMPTY Planning column must still cascade to the end.
    await page.request.post(`/api/boards/${board.id}/cards/${card.id}/move`, {
      data: { to_column_id: col("Planning").id },
    });

    let columnName = "";
    let status = "";
    for (let i = 0; i < 60; i += 1) {
      const s = await (await page.request.get(`/api/boards/${board.id}`)).json();
      const c = (s.cards as { id: string; column_id: string; run_status: string }[]).find(
        (x) => x.id === card.id,
      );
      const columns: { id: string; name: string }[] = s.columns;
      columnName = columns.find((x) => x.id === c?.column_id)?.name ?? "";
      status = c?.run_status ?? "";
      if (columnName === "Done" && status === "success") break;
      if (status === "failed") break;
      await page.waitForTimeout(500);
    }
    expect(status).toBe("success");
    expect(columnName).toBe("Done");
  } finally {
    await deleteAllBoards(page);
    await deleteWorkflow(page, wf.id);
  }
});

test("opens card detail and posts a comment", async ({ page }) => {
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await page.getByPlaceholder("Board name").fill("Comment board");
  await page.getByRole("button", { name: "Create board" }).click();

  const backlog = page.getByTestId("board-column-Backlog");
  await backlog.getByPlaceholder("Add a card").fill("Plan the beta");
  await backlog.getByPlaceholder("Add a card").press("Enter");
  await backlog.getByText("Plan the beta").click();

  await page.getByTestId("card-comment-input").fill("Focus on developer onboarding");
  await page.getByTestId("card-comment-submit").click();
  await expect(page.getByText("Focus on developer onboarding")).toBeVisible();
});
