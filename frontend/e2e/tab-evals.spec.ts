import { expect, test } from "@playwright/test";

import {
  acceptNextDialog,
  clearEvalSuites,
  deleteEvalSuite,
  prepareAuthenticatedPage,
} from "./support";

// These tests share one account's eval suites and assert on the global empty
// state, so they must not run concurrently with each other under --fully-parallel.
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await clearEvalSuites(page);
});

test("creates and deletes an eval suite", async ({ page }) => {
  await page.goto("/evals");
  await expect(page.getByText("Create a suite to get started")).toBeVisible();
  await page.getByRole("button", { name: "Create your first suite" }).click();
  await expect(page.getByTestId("eval-suite-name")).toHaveValue("New Eval Suite");

  await acceptNextDialog(
    page,
    () => page.getByTitle("Delete suite").click(),
    "Are you sure you want to delete this eval suite? This cannot be undone.",
  );
  await expect(page.getByText("Create a suite to get started")).toBeVisible();
});

test("edits the suite name and system prompt with autosave", async ({ page }) => {
  const newName = `E2E Suite ${Date.now()}`;
  const systemPrompt = "You are a helpful Playwright assistant.";

  await page.goto("/evals");
  const suiteResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/evals/suites",
  );
  await page.getByRole("button", { name: "Create your first suite" }).click();
  const suite = (await (await suiteResponsePromise).json()) as { id: string };

  try {
    // Editing the name auto-saves via a PATCH to the suite.
    const namePatchPromise = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        new URL(response.url()).pathname === `/api/evals/suites/${suite.id}`,
    );
    await page.getByTestId("eval-suite-name").fill(newName);
    await page.getByTestId("eval-suite-name").blur();
    expect((await namePatchPromise).ok()).toBeTruthy();

    // Editing the system prompt auto-saves via another PATCH.
    const promptPatchPromise = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        new URL(response.url()).pathname === `/api/evals/suites/${suite.id}`,
    );
    await page.getByPlaceholder("Enter your system prompt...").fill(systemPrompt);
    await page.getByPlaceholder("Enter your system prompt...").blur();
    expect((await promptPatchPromise).ok()).toBeTruthy();

    // Reload selects the suite and shows the persisted name.
    await page.reload();
    await expect(page.getByTestId("eval-suite-name")).toHaveValue(newName);
  } finally {
    await deleteEvalSuite(page, suite.id);
  }
});
