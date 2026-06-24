import { expect, test } from "@playwright/test";

import { acceptNextDialog, expectOk, prepareAuthenticatedPage } from "./support";

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

test("creates and deletes a Linear credential", async ({ page }) => {
  const credentialName = `e2e-linear-${Date.now()}`;

  await openCredentialDialog(page);
  await page.getByLabel("Name").fill(credentialName);
  await page.locator("#cred-type select").selectOption("linear");
  await page.getByLabel("API Key").fill("lin_api_e2e_test");
  await expect(page.getByTestId("linear-test-connection-button")).toBeVisible();

  await page.route("**/api/credentials/test", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        message: "Connected as E2E User",
      }),
    });
  });

  const testResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/credentials/test",
  );
  await page.getByTestId("linear-test-connection-button").click();
  await testResponsePromise;
  await expect(page.getByText("Connected as E2E User")).toBeVisible();

  const credentialResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/credentials",
  );
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const credential = (await (await credentialResponsePromise).json()) as { id: string };

  const credentialCard = page.getByTestId(`credential-card-${credential.id}`);
  await expect(credentialCard).toContainText(credentialName);
  await expect(credentialCard).toContainText("Linear");
  await acceptNextDialog(
    page,
    () => page.getByTestId(`credential-delete-${credential.id}`).click(),
    "Are you sure you want to delete this credential?",
  );
  await expect(credentialCard).toBeHidden();
});

test("shows Linear test connection failure message", async ({ page }) => {
  await openCredentialDialog(page);
  await page.getByLabel("Name").fill(`e2e-linear-fail-${Date.now()}`);
  await page.locator("#cred-type select").selectOption("linear");
  await page.getByLabel("API Key").fill("lin_api_invalid");

  await page.route("**/api/credentials/test", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: false,
        message: "Linear API error: Not authorized",
      }),
    });
  });

  await page.getByTestId("linear-test-connection-button").click();
  await expect(
    page.locator(".text-xs.text-destructive", {
      hasText: "Linear API error: Not authorized",
    }),
  ).toBeVisible();
});

test("tests an existing Linear credential without re-entering the API key", async ({ page }) => {
  const credentialName = `e2e-linear-edit-${Date.now()}`;
  const createResponse = await page.request.post("/api/credentials", {
    data: {
      name: credentialName,
      type: "linear",
      config: { api_key: "lin_api_e2e_stored" },
    },
  });
  await expectOk(createResponse);
  const credential = (await createResponse.json()) as { id: string };

  try {
    await page.goto("/?tab=credentials");
    await page.getByTestId(`credential-card-${credential.id}`).click();
    await expect(page.getByRole("heading", { name: "Edit Credential" })).toBeVisible();

    await page.route("**/api/credentials/test", async (route) => {
      const payload = route.request().postDataJSON() as {
        type?: string;
        config?: { api_key?: string };
        credential_id?: string;
      };
      expect(payload.type).toBe("linear");
      expect(payload.credential_id).toBe(credential.id);
      expect(payload.config?.api_key ?? "").toBe("");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Connected as Stored User",
        }),
      });
    });

    await page.getByTestId("linear-test-connection-button").click();
    await expect(page.getByText("Connected as Stored User")).toBeVisible();
  } finally {
    await page.request.delete(`/api/credentials/${credential.id}`);
  }
});
