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

test("closes the new board dialog on Escape", async ({ page }) => {
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await expect(page.getByPlaceholder("Board name")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByPlaceholder("Board name")).not.toBeVisible();
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
