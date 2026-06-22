import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

// Creating a vector store provisions a QDrant collection, which is not available
// in the E2E environment, so these tests cover the panel UI and create-dialog
// validation rather than an actual store lifecycle.

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows the vector stores empty state", async ({ page }) => {
  await page.goto("/?tab=vectorstores");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Vector Stores", exact: true })).toBeVisible();
  await expect(main.getByRole("heading", { name: "No vector stores yet" })).toBeVisible();
  await expect(main.getByText("Create a vector store to start using RAG in your workflows")).toBeVisible();
  await expect(main.getByRole("button", { name: "New Vector Store" })).toBeVisible();
});

test("opens the create dialog and guards submission without a credential", async ({ page }) => {
  await page.goto("/?tab=vectorstores");
  await page.getByRole("button", { name: "New Vector Store" }).click();

  // The dialog opens with a name field.
  await expect(page.getByRole("heading", { name: "New Vector Store" })).toBeVisible();
  await page.locator("#store-name").fill(`E2E Store ${Date.now()}`);

  // With no QDrant credential, the dialog surfaces the requirement and keeps the
  // Create button disabled.
  await expect(page.getByText("No QDrant credentials found.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create", exact: true })).toBeDisabled();

  // Cancel closes the dialog.
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("heading", { name: "New Vector Store" })).toBeHidden();
});
