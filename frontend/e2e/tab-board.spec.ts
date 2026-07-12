import { expect, test } from "@playwright/test";

import { deleteAllBoards, prepareAuthenticatedPage } from "./support";

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
