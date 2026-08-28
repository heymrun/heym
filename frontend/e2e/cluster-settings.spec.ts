import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

/**
 * These specs guard existing single-instance installs.
 *
 * The Instances settings tab is gated on HEYM_ADMIN_EMAILS, which this harness
 * does not set, so the admin panel itself is exercised by the backend tests and
 * by manual verification rather than here. What matters for everyone else is
 * that load distribution stays invisible until a cluster actually exists.
 */
test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("the Instances tab is hidden for a non-admin account", async ({ page }) => {
  await page.goto("/");
  await page.getByTitle("Settings").click();

  await expect(page.getByRole("button", { name: "Profile" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Instances" })).toHaveCount(0);
});

test("run history shows no instance filter without a cluster", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();

  // No run carries an instance, so the select never renders.
  await expect(page.getByLabel("Clear instance filter")).toHaveCount(0);
});
