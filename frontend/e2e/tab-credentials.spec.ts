import { expect, test } from "@playwright/test";

import { acceptNextDialog, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

async function openCredentialDialog(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/?tab=credentials");
  await expect(
    page.getByRole("main").getByRole("heading", { name: "Credentials", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /New Credential|Add Credential/ }).first().click();
}

test("creates and deletes a bearer credential", async ({ page }) => {
  const credentialName = `e2e-bearer-${Date.now()}`;

  await openCredentialDialog(page);
  await page.getByLabel("Name").fill(credentialName);
  await page.locator("#cred-type select").selectOption("bearer");
  await page.getByLabel("Bearer Token").fill("e2e-secret-token");

  const credentialResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/credentials",
  );
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const credential = (await (await credentialResponsePromise).json()) as { id: string };

  const credentialCard = page.getByTestId(`credential-card-${credential.id}`);
  await expect(credentialCard).toBeVisible();
  await acceptNextDialog(
    page,
    () => page.getByTestId(`credential-delete-${credential.id}`).click(),
    "Are you sure you want to delete this credential?",
  );
  await expect(credentialCard).toBeHidden();
});

test("creates a header credential with type-specific fields and deletes it", async ({ page }) => {
  const credentialName = `e2e-header-${Date.now()}`;

  await openCredentialDialog(page);
  await page.getByLabel("Name").fill(credentialName);

  // Switching the type swaps in type-specific fields (Header Key/Value).
  await page.locator("#cred-type select").selectOption("header");
  await page.getByLabel("Header Key").fill("X-Custom-Header");
  await page.getByLabel("Header Value").fill("e2e-header-value");

  const credentialResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/credentials",
  );
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const credential = (await (await credentialResponsePromise).json()) as { id: string };

  const credentialCard = page.getByTestId(`credential-card-${credential.id}`);
  await expect(credentialCard).toBeVisible();
  await expect(credentialCard).toContainText(credentialName);

  await acceptNextDialog(
    page,
    () => page.getByTestId(`credential-delete-${credential.id}`).click(),
    "Are you sure you want to delete this credential?",
  );
  await expect(credentialCard).toBeHidden();
});
