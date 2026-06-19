import type { Page } from "@playwright/test";

export async function mockVersionCheck(page: Page): Promise<void> {
  await page.route("**/api/version**", async (route) => {
    await route.fulfill({
      json: {
        version: "0.0.46",
        latest_version: null,
        update_available: false,
        release_url: null,
        compare_url: null,
        compare_label: null,
        source: "e2e",
        checked_at: null,
        error: null,
      },
    });
  });
}
