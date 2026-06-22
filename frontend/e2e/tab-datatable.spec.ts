import { expect, test } from "@playwright/test";

import { createDataTable, deleteDataTable, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("creates a data table from the UI and opens its detail view", async ({ page }) => {
  const tableName = `E2E Table ${Date.now()}`;
  let tableId: string | undefined;

  try {
    await page.goto("/?tab=datatable");
    await page.getByRole("button", { name: "New DataTable", exact: true }).click();

    // Fill the create dialog and submit.
    await expect(page.getByRole("heading", { name: "New DataTable", exact: true })).toBeVisible();
    await page.getByPlaceholder("My Table").fill(tableName);
    await page.getByRole("button", { name: "Create", exact: true }).click();

    // Creating navigates straight into the new table's detail view.
    await expect(page).toHaveURL(/tab=datatable(\/|%2F)[0-9a-f-]+/);
    tableId = decodeURIComponent(page.url()).split("datatable/").pop();
    await expect(page.getByRole("heading", { name: tableName, exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Add Row" })).toBeVisible();

    // The new table is also listed back on the list view.
    await page.goto("/?tab=datatable");
    await expect(page.getByText(tableName, { exact: true })).toBeVisible();
  } finally {
    if (tableId) {
      await deleteDataTable(page, tableId);
    }
  }
});

test("adds and deletes a row in a seeded table", async ({ page }) => {
  const table = await createDataTable(page, `E2E Rows ${Date.now()}`, [
    { name: "title", type: "string", order: 0 },
    { name: "qty", type: "number", order: 1 },
  ]);

  try {
    await page.goto(`/?tab=datatable/${table.id}`);
    await expect(page.getByRole("heading", { name: table.name, exact: true })).toBeVisible();

    // Both seeded columns are rendered in the column bar.
    const columnsBar = page.locator("text=Columns:").locator("..");
    await expect(columnsBar.getByText("title", { exact: true })).toBeVisible();
    await expect(columnsBar.getByText("qty", { exact: true })).toBeVisible();
    await expect(page.getByText('No rows yet. Click "Add Row" to get started.')).toBeVisible();

    // Add a row via the inline editor.
    await page.getByRole("button", { name: "Add Row" }).click();
    await page.getByPlaceholder("title").fill("hello-row");
    await page.getByPlaceholder("qty (number)").fill("7");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    const dataRow = page.locator("tbody tr", { hasText: "hello-row" });
    await expect(dataRow).toBeVisible();
    await expect(dataRow.getByText("7", { exact: true })).toBeVisible();

    // Delete the row (last action button in the row) -> back to empty state.
    await dataRow.getByRole("button").last().click();
    await expect(page.getByText("hello-row")).toBeHidden();
    await expect(page.getByText('No rows yet. Click "Add Row" to get started.')).toBeVisible();
  } finally {
    await deleteDataTable(page, table.id);
  }
});
