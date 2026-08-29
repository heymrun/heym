import { expect, test } from "@playwright/test";

import { RELEASE_REGISTRY } from "../src/features/release-tour/releaseRegistry";
import { buildReleaseTourCatalog, buildReleaseTours } from "../src/features/release-tour/releaseTourMapper";
import { prepareAuthenticatedPage } from "./support";

// Assert against the shipped registry so adding a section never breaks this spec.
const RELEASE_TOUR = buildReleaseTours(RELEASE_REGISTRY)[0]!;
const RELEASE_CATALOG = buildReleaseTourCatalog(RELEASE_REGISTRY)!;

test("auto-opens the release tour and can be dismissed", async ({ page }) => {
  await prepareAuthenticatedPage(page, { allowReleaseTour: true });
  await page.goto("/");

  const tour = page.getByRole("dialog", { name: /New in Heym/ });
  await expect(tour).toBeVisible();
  await expect(
    tour.getByRole("heading", { name: RELEASE_TOUR.introTitle }),
  ).toBeVisible();

  await tour.getByRole("button", { name: "Start tour" }).click();
  await expect(
    tour.getByRole("heading", { name: RELEASE_TOUR.slides[0].title }),
  ).toBeVisible();

  await tour.getByRole("button", { name: "Close what's new" }).click();
  await expect(tour).toBeHidden();
  await expect(page.getByRole("button", { name: "New in Heym — open the release tour" })).toBeVisible();
});

test("does not auto-open when the current release is already seen", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await page.goto("/");

  await expect(page.getByRole("button", { name: "New in Heym — open the release tour" })).toBeVisible();
  // Auto-open is delayed 900ms; wait past it so a missed seen-seed still fails this test.
  await page.waitForTimeout(1_200);
  await expect(page.getByRole("dialog", { name: /New in Heym/ })).toHaveCount(0);
});

test("opens every shipped feature from the launcher", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await page.goto("/");

  await page.getByRole("button", { name: "New in Heym — open the release tour" }).click();

  const tour = page.getByRole("dialog", { name: /New in Heym/ });
  await expect(tour.getByRole("heading", { name: RELEASE_CATALOG.introTitle })).toBeVisible();
  await tour.getByRole("button", { name: "Start tour" }).click();
  await expect(
    tour.getByRole("heading", { name: RELEASE_CATALOG.slides[0].title }),
  ).toBeVisible();
});
