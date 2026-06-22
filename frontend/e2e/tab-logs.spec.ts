import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("renders the Docker logs viewer controls", async ({ page }) => {
  await page.goto("/?tab=logs");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Docker Logs", exact: true })).toBeVisible();
  await expect(main.getByRole("button", { name: "Refresh" })).toBeVisible();
  await expect(
    page.getByPlaceholder("Filter logs... (type to filter log content)"),
  ).toBeVisible();
});

test("toggles the search filter indicator", async ({ page }) => {
  await page.goto("/?tab=logs");
  await expect(page.getByRole("heading", { name: "Docker Logs", exact: true })).toBeVisible();

  const filter = page.getByPlaceholder("Filter logs... (type to filter log content)");

  // Typing a query surfaces the active-filter indicator.
  await filter.fill("error");
  await expect(filter).toHaveValue("error");
  await expect(page.getByText(/Filtering by:/)).toBeVisible();

  // The inline clear button resets the filter and hides the indicator.
  await filter.locator("xpath=following-sibling::button").click();
  await expect(filter).toHaveValue("");
  await expect(page.getByText(/Filtering by:/)).toBeHidden();
});
