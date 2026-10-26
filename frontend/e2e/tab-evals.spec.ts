import { expect, test, type Page } from "@playwright/test";

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
  await page.getByRole("button", { name: "Prompt suite" }).click();
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
  await page.getByRole("button", { name: "Prompt suite" }).click();
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

async function createPromptSuite(page: Page, name: string): Promise<string> {
  const response = await page.request.post("/api/evals/suites", { data: { name } });
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { id: string }).id;
}

test("a selected suite shows its loading state, never the empty state", async ({ page }) => {
  const suiteId = await createPromptSuite(page, "QA Evals");
  let release = (): void => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/evals/suites/${suiteId}`, async (route) => {
    if (route.request().method() === "GET") await held;
    await route.continue();
  });

  await page.goto(`/evals?suite=${suiteId}`);
  await expect(page.getByTestId("eval-suite-loading")).toBeVisible();
  await expect(page.getByText("Create a suite to get started")).toHaveCount(0);

  release();
  await expect(page.getByTestId("eval-suite-name")).toHaveValue("QA Evals");
});

test("a suite that fails to load offers a retry instead of the empty state", async ({ page }) => {
  const suiteId = await createPromptSuite(page, "QA Evals");
  let failing = true;
  await page.route(`**/api/evals/suites/${suiteId}`, async (route) => {
    if (failing && route.request().method() === "GET") {
      await route.fulfill({ status: 500, json: { detail: "boom" } });
      return;
    }
    await route.continue();
  });

  await page.goto(`/evals?suite=${suiteId}`);
  await expect(page.getByText("Could not load this suite.")).toBeVisible();
  await expect(page.getByText("Create a suite to get started")).toHaveCount(0);

  failing = false;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByTestId("eval-suite-name")).toHaveValue("QA Evals");
});

test("a slow answer for the previous suite does not replace the selected one", async ({ page }) => {
  const firstId = await createPromptSuite(page, "First suite");
  await createPromptSuite(page, "Second suite");
  let release = (): void => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/evals/suites/${firstId}`, async (route) => {
    if (route.request().method() === "GET") await held;
    await route.continue();
  });

  await page.goto(`/evals?suite=${firstId}`);
  // The picker's options carry the suite type as a hint, so match the name's start.
  const picker = page.getByTestId("eval-suite-select").getByRole("combobox");
  await picker.click();
  await picker.fill("Second");
  await page.getByRole("option", { name: /^Second suite/ }).click();
  await expect(page.getByTestId("eval-suite-name")).toHaveValue("Second suite");

  const firstAnswer = page.waitForResponse((response) =>
    response.url().endsWith(`/api/evals/suites/${firstId}`),
  );
  release();
  await firstAnswer;
  await expect(page.getByTestId("eval-suite-name")).toHaveValue("Second suite");
});
