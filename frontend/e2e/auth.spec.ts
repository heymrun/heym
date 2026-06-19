import { expect, test } from "@playwright/test";

import { E2E_USER, prepareAuthenticatedPage } from "./support";

test.use({ storageState: { cookies: [], origins: [] } });
test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("redirects protected pages to login", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("shows an error for invalid credentials", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email address").fill("missing@heym.example.com");
  await page.getByLabel("Password").fill("WrongPassword123");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Invalid email or password")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("logs in and logs out through the UI", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(E2E_USER.email);
  await page.getByLabel("Password").fill(E2E_USER.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL("/");
  await page.getByRole("button", { name: "Logout" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("validates registration before sending the request", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Validation User");
  await page.getByLabel("Email address").fill("validation@heym.example.com");
  await page.getByLabel("Password", { exact: true }).fill("short");
  await page.getByLabel("Confirm").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByText("Password must be at least 8 characters")).toBeVisible();
});

test("registers a user and opens the dashboard", async ({ page }) => {
  const email = `browser-${Date.now()}@heym.example.com`;

  await page.goto("/register");
  await page.getByLabel("Full name").fill("Browser User");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("BrowserTest123");
  await page.getByLabel("Confirm").fill("BrowserTest123");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL("/");
  await expect(
    page.getByRole("main").getByRole("heading", { name: "Workflows" }),
  ).toBeVisible();
});
