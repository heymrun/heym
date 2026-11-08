import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await page.setViewportSize({ width: 1280, height: 800 });
});

test("settings dialog lists its tabs vertically on the left of the view", async ({ page }) => {
  await page.goto("/");
  await page.getByTitle("Settings").click();

  const profileTab = page.getByRole("button", { name: "Profile", exact: true });
  const securityTab = page.getByRole("button", { name: "Security", exact: true });
  await expect(profileTab).toBeVisible();
  await expect(securityTab).toBeVisible();

  // Tabs stack: Security sits below Profile in the same column.
  const profileBox = await profileTab.boundingBox();
  const securityBox = await securityTab.boundingBox();
  expect(profileBox).not.toBeNull();
  expect(securityBox).not.toBeNull();
  expect(securityBox!.y).toBeGreaterThan(profileBox!.y + profileBox!.height - 1);
  expect(Math.abs(securityBox!.x - profileBox!.x)).toBeLessThan(2);

  // The selected tab carries the underline.
  await expect(profileTab).toHaveAttribute("aria-current", "true");
  await expect(securityTab).not.toHaveAttribute("aria-current", "true");
  await expect(profileTab).toHaveClass(/border-primary/);

  // The view opens to the right of the tab rail.
  const profileView = page.getByText("Your picture comes from");
  await expect(profileView).toBeVisible();
  const viewBox = await profileView.boundingBox();
  expect(viewBox).not.toBeNull();
  expect(viewBox!.x).toBeGreaterThan(profileBox!.x + profileBox!.width);
});

test("clicking a tab opens its view on the right and moves the underline", async ({ page }) => {
  await page.goto("/");
  await page.getByTitle("Settings").click();

  const profileTab = page.getByRole("button", { name: "Profile", exact: true });
  const securityTab = page.getByRole("button", { name: "Security", exact: true });

  await securityTab.click();

  await expect(page.getByText("Your picture comes from")).toBeHidden();
  await expect(securityTab).toHaveAttribute("aria-current", "true");
  await expect(securityTab).toHaveClass(/border-primary/);
  await expect(profileTab).not.toHaveAttribute("aria-current", "true");

  const securityBox = await securityTab.boundingBox();
  const passwordField = page.getByLabel("Current Password");
  await expect(passwordField).toBeVisible();
  const fieldBox = await passwordField.boundingBox();
  expect(fieldBox!.x).toBeGreaterThan(securityBox!.x + securityBox!.width);
});
