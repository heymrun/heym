import { expect, test } from "@playwright/test";

import { acceptNextDialog, deleteTeam, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

async function createTeamViaUi(
  page: import("@playwright/test").Page,
  name: string,
): Promise<{ id: string }> {
  await page.goto("/?tab=teams");
  await expect(page.getByRole("main").getByRole("heading", { name: "Teams", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /New Team|Create Team/ }).first().click();
  await page.getByLabel("Name").fill(name);

  const teamResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/teams",
  );
  await page.getByRole("button", { name: "Create", exact: true }).click();
  return (await (await teamResponsePromise).json()) as { id: string };
}

test("creates a team and opens its detail dialog", async ({ page }) => {
  const teamName = `E2E Team ${Date.now()}`;
  const team = await createTeamViaUi(page, teamName);

  try {
    const teamCard = page.getByText(teamName, { exact: true });
    await expect(teamCard).toBeVisible();

    // Opening the card shows the detail dialog (which exposes member management).
    await teamCard.click();
    await expect(page.getByTitle("Delete team")).toBeVisible();
  } finally {
    await deleteTeam(page, team.id);
  }
});

test("creates and deletes a team", async ({ page }) => {
  const teamName = `E2E Team Del ${Date.now()}`;
  const team = await createTeamViaUi(page, teamName);

  try {
    const teamCard = page.getByText(teamName, { exact: true });
    await expect(teamCard).toBeVisible();
    await teamCard.click();

    const deletePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "DELETE" &&
        new URL(response.url()).pathname === `/api/teams/${team.id}`,
    );
    await acceptNextDialog(
      page,
      () => page.getByTitle("Delete team").click(),
      "Delete this team? All team shares will be removed.",
    );
    await deletePromise;

    // The team card (an h3) is removed from the grid (the dialog title is an h2).
    await expect(page.getByRole("heading", { name: teamName, level: 3 })).toBeHidden();
  } finally {
    await deleteTeam(page, team.id);
  }
});
