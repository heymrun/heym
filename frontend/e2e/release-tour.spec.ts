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

test("every feature's animation fits inside its frame", async ({ page }, testInfo) => {
  await prepareAuthenticatedPage(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "New in Heym — open the release tour" }).click();
  const tour = page.getByRole("dialog", { name: /New in Heym/ });
  await tour.getByRole("button", { name: "Start tour" }).click();
  const frame = tour.getByTestId("release-tour-visual");

  for (const [index, slide] of RELEASE_CATALOG.slides.entries()) {
    await tour.getByRole("button", { name: `Go to ${slide.title}`, exact: true }).click();
    await expect(tour.getByRole("heading", { name: slide.title })).toBeVisible();
    // Sample the loop a few times: some animations grow from one step to the next.
    for (let sample = 0; sample < 4; sample += 1) {
      await page.waitForTimeout(800);
      const overflow = await frame.evaluate((root) => {
        const box = root.getBoundingClientRect();
        return Array.from(root.querySelectorAll("*"))
          .map((element) => ({ element, rect: element.getBoundingClientRect() }))
          .filter(({ rect }) => rect.width > 0 && rect.height > 0)
          .filter(
            ({ rect }) =>
              rect.top < box.top - 1 ||
              rect.left < box.left - 1 ||
              rect.bottom > box.bottom + 1 ||
              rect.right > box.right + 1,
          )
          .map(({ element }) => (element.textContent ?? element.tagName).trim().slice(0, 40));
      });
      expect(overflow, `${slide.title}, sample ${sample}`).toEqual([]);
    }
    await frame.screenshot({ path: testInfo.outputPath(`visual-${index}.png`), animations: "disabled" });
  }
});
