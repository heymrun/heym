import { expect, test } from "@playwright/test";

import { acceptNextDialog, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("creates, edits, and deletes a global variable", async ({ page }) => {
  const variableName = `e2eVariable${Date.now()}`;
  const initialValue = "playwright-value";
  const updatedValue = "playwright-updated";

  await page.goto("/?tab=globalvariables");
  await expect(
    page.getByRole("heading", { name: "Global Variables", exact: true }),
  ).toBeVisible();

  // Create
  await page.getByRole("button", { name: /New Variable|Add Variable/ }).first().click();
  await page.getByLabel("Name").fill(variableName);
  await page.getByLabel("Value", { exact: true }).fill(initialValue);
  await page.getByRole("button", { name: "Create", exact: true }).click();

  const variableRow = page.getByTestId(`global-variable-${variableName}`);
  await expect(variableRow).toContainText(initialValue);

  // Edit: opening the row reveals the edit dialog prefilled with the value.
  await variableRow.click();
  const valueField = page.getByLabel("Value", { exact: true });
  await expect(valueField).toHaveValue(initialValue);
  await valueField.fill(updatedValue);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(variableRow).toContainText(updatedValue);

  // Delete
  await acceptNextDialog(
    page,
    () => variableRow.getByTitle("Delete").click(),
    "Are you sure you want to delete this variable?",
  );
  await expect(variableRow).toBeHidden();
});

test("persists a created variable across a page reload", async ({ page }) => {
  const variableName = `e2ePersist${Date.now()}`;
  const variableValue = "persist-me";

  await page.goto("/?tab=globalvariables");
  await page.getByRole("button", { name: /New Variable|Add Variable/ }).first().click();
  await page.getByLabel("Name").fill(variableName);
  await page.getByLabel("Value", { exact: true }).fill(variableValue);
  await page.getByRole("button", { name: "Create", exact: true }).click();

  const variableRow = page.getByTestId(`global-variable-${variableName}`);
  await expect(variableRow).toContainText(variableValue);

  // The variable survives a full reload (it is server-persisted, not local state).
  await page.reload();
  await expect(variableRow).toContainText(variableValue);

  await acceptNextDialog(
    page,
    () => variableRow.getByTitle("Delete").click(),
    "Are you sure you want to delete this variable?",
  );
  await expect(variableRow).toBeHidden();
});
