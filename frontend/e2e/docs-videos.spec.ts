import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

for (const [slug, title, recording] of [
  ["board-tab", "Kanban Board", "board"],
  ["alerts-tab", "Alerts", "alerts"],
  ["dashboard-tab", "Dashboard", "dashboard"],
]) {
  test(`opens the ${title} documentation and loads its demo`, async ({ page }) => {
    await prepareAuthenticatedPage(page);
    await page.goto("/docs");

    const navigation = page.getByRole("navigation", { name: "Documentation navigation" });
    await navigation.getByRole("link", { name: title, exact: true }).click();
    await expect(page).toHaveURL(`/docs/tabs/${slug}`);

    const video = page.locator(`.doc-content video[src="/features/showcase/${recording}.webm"]`);
    await expect(video).toBeVisible();
    await expect(video).toHaveAttribute("controls", "");
    await expect.poll(async () => video.evaluate((element: HTMLVideoElement) =>
      element.readyState >= 1 && element.videoWidth > 0,
    )).toBe(true);
  });
}

test("includes Board, Alerts and Dashboard demos in the features reference", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await page.goto("/docs/reference/features");

  for (const recording of ["board", "alerts", "dashboard"]) {
    await expect(
      page.locator(`.doc-content video[src="/features/showcase/${recording}.webm"]`),
    ).toBeVisible();
  }
});
