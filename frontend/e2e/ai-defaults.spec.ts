import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("opens the AI Defaults settings tab and saves a preference", async ({ page }) => {
  await page.goto("/");

  // The header Settings button is an icon+name button whose accessible name is
  // the user's name; target its stable title attribute instead.
  await page.getByTitle("Settings").click();

  // Switch to the AI Defaults tab (the dialog uses plain divs, so scope by text).
  await page.getByRole("button", { name: "AI Defaults" }).click();

  await expect(page.getByText("Preferred LLM credential")).toBeVisible();
  const saveButton = page.getByRole("button", { name: "Save AI Defaults" });
  await expect(saveButton).toBeVisible();

  // Saving with "No preference" persists and closes the dialog without error.
  await saveButton.click();
  await expect(page.getByText("Preferred LLM credential")).toBeHidden();

  // Reopen and confirm the tab still renders cleanly.
  await page.getByTitle("Settings").click();
  await page.getByRole("button", { name: "AI Defaults" }).click();
  await expect(page.getByText("Preferred LLM credential")).toBeVisible();
});
