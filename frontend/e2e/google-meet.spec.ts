import { expect, test } from "@playwright/test";

import { createWorkflow, deleteCredential, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test("Google Meet credentials connect through their Calendar OAuth endpoint", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await page.route("**/api/credentials/google-meet/oauth/authorize", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ auth_url: "https://accounts.google.com/o/oauth2/v2/auth?client_id=e2e-dummy" }),
  }));
  await page.goto("/?tab=credentials");
  await page.getByRole("button", { name: /New Credential|Add Credential/ }).first().click();
  await page.getByLabel("Name", { exact: true }).fill(`e2e-google-meet-${Date.now()}`);
  const type = page.locator("#cred-type");
  await type.click();
  await type.fill("Google Meet (OAuth2)");
  await page.getByRole("option", { name: "Google Meet (OAuth2)", exact: true }).click();
  await page.locator("#cred-gm-client-id").fill("e2e-client.apps.googleusercontent.com");
  await page.locator("#cred-gm-client-secret").fill("e2e-dummy-client-secret");
  // Exercise the existing blocked-popup fallback, without navigating to Google.
  await page.evaluate(() => { window.open = () => null; });
  const saved = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/credentials");
  const authorized = page.waitForRequest("**/api/credentials/google-meet/oauth/authorize");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const credential = await (await saved).json() as { id: string; type: string; masked_value: string };
  try {
    expect(credential.type).toBe("google_meet");
    const request = await authorized;
    expect(request.postDataJSON()).toEqual({ credential_id: credential.id });
    await expect(page.getByRole("link", { name: "Open the authorization page" })).toHaveAttribute(
      "href", "https://accounts.google.com/o/oauth2/v2/auth?client_id=e2e-dummy",
    );
    expect(JSON.stringify(credential)).not.toContain("e2e-dummy-client-secret");
  } finally {
    await deleteCredential(page, credential.id);
  }
});

test("Google Meet exposes availability, booking fields and expression navigation", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  const workflow = await createWorkflow(page, `Google Meet ${Date.now()}`, [{
    id: "meeting", type: "googleMeet", position: { x: 120, y: 160 },
    data: { label: "Booking", credentialId: "", gmOperation: "read", gmCalendarId: "primary", gmTimeZone: "UTC" },
  }]);
  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator('.vue-flow__node[data-id="meeting"]')).toBeVisible();
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="meeting"]').click();
    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("gm-field-gmEndDate")).toBeVisible();
    const includeTitles = panel.getByLabel("Include Busy Event Titles", { exact: true });
    await expect(includeTitles).not.toBeChecked();
    await includeTitles.check();
    await expect(includeTitles).toBeChecked();
    await expect(panel.getByTestId("gm-field-gmAttendees")).toHaveCount(0);
    await panel.getByTestId("gm-operation-field").locator("select").selectOption("create");
    await expect(panel.getByTestId("gm-field-gmAttendees")).toBeVisible();
    await expect(panel.getByTestId("gm-field-gmTitle")).toBeVisible();
    await expect(panel.getByTestId("gm-field-gmDescription")).toBeVisible();
    await expect(panel.getByTestId("gm-field-gmStartTime")).toBeVisible();
    await expect(panel.getByTestId("gm-field-gmEndTime")).toBeVisible();
    await expect(panel.getByTestId("gm-field-gmEndDate")).toHaveCount(0);
    await expect(panel.getByTestId("gm-busy-titles-option")).toHaveCount(0);
    await panel.getByTestId("gm-field-gmAttendees").locator("textarea").fill("$input.email");
    await panel.getByTestId("gm-operation-field").locator("select").selectOption("update");
    await expect(panel.getByTestId("gm-field-gmEventId")).toBeVisible();
    await panel.getByTestId("gm-operation-field").locator("select").selectOption("delete");
    await expect(panel.getByTestId("gm-field-gmEventId")).toBeVisible();
    await expect(panel.getByTestId("gm-field-gmAttendees")).toHaveCount(0);
    await panel.getByTestId("gm-operation-field").locator("select").selectOption("read");
    await expect(includeTitles).toBeChecked();
    await includeTitles.uncheck();
    await panel.getByTestId("gm-operation-field").locator("select").selectOption("delete");
    await page.locator('.vue-flow__node[data-id="meeting"]').dblclick();
    await expect(page.getByRole("heading", { name: "Booking – Calendar ID or Email", exact: true })).toBeVisible();
    await expect(page.getByText("1 / 2", { exact: true })).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
