import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows the traces empty state and filter controls", async ({ page }) => {
  await page.goto("/?tab=traces");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Traces", exact: true })).toBeVisible();
  await expect(main.getByText("No traces yet.", { exact: true })).toBeVisible();
  await expect(main.getByText("Time range", { exact: true })).toBeVisible();
  await expect(main.getByRole("button", { name: "Refresh" })).toBeVisible();
});

test("reloads traces on time range change and toggles the search box", async ({ page }) => {
  await page.goto("/?tab=traces");
  await expect(page.getByRole("main").getByRole("heading", { name: "Traces" })).toBeVisible();

  // Changing the time range refetches traces with the new range.
  const tracesReloadPromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === "/api/traces",
  );
  await page.locator('select:has(option[value="1h"])').selectOption("24h");
  expect((await tracesReloadPromise).ok()).toBeTruthy();

  // The search box is collapsed by default; the toggle (the icon button before
  // Refresh) reveals it, accepts text, and exposes a clear button.
  const searchToggle = page
    .getByRole("button", { name: "Refresh" })
    .locator("xpath=preceding-sibling::button[1]");
  await searchToggle.click();

  const search = page.getByPlaceholder("Search traces by model, workflow, credential, node...");
  await expect(search).toBeVisible();
  await search.fill("gpt-4o");
  await expect(search).toHaveValue("gpt-4o");
  const clearButton = search.locator("xpath=following-sibling::button");
  await expect(clearButton).toBeVisible();
  await clearButton.click();
  await expect(search).toHaveValue("");
});
