import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("opens the AI Defaults settings tab and saves a preference", async ({ page }) => {
  await page.goto("/");

  // Open the Settings dialog from the header.
  await page.getByRole("button", { name: "Settings" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // Switch to the AI Defaults tab.
  await dialog.getByRole("button", { name: "AI Defaults" }).click();

  // The preferred-credential section renders.
  await expect(dialog.getByText("Preferred LLM credential")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Save AI Defaults" })).toBeVisible();

  // Saving with "No preference" closes the dialog without error.
  await dialog.getByRole("button", { name: "Save AI Defaults" }).click();
  await expect(dialog).toBeHidden();

  // Reopen and confirm the tab still opens cleanly.
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "AI Defaults" }).click();
  await expect(page.getByRole("dialog").getByText("Preferred LLM credential")).toBeVisible();
});
