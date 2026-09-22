import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, expectOk, prepareAuthenticatedPage } from "./support";

test("uses create-time execution tokens without treating metadata as bearer values", async ({ page, context }) => {
  await prepareAuthenticatedPage(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.setViewportSize({ width: 1600, height: 1000 });
  const workflow = await createWorkflow(page, `Token cURL ${Date.now()}`, [
    { id: "input", type: "textInput", position: { x: 0, y: 0 }, data: { label: "input" } },
  ]);
  const endpoint = `/api/workflows/${workflow.id}/execution-tokens`;

  try {
    const existingResponse = await page.request.post(endpoint, { data: { ttl_seconds: 3600 } });
    await expectOk(existingResponse);
    const existing = await existingResponse.json() as { id: string; token: string };
    const listResponse = await page.request.get(endpoint);
    await expectOk(listResponse);
    const listed = await listResponse.json() as { id: string; token?: string }[];
    expect(listed.find((token) => token.id === existing.id)).not.toHaveProperty("token");
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByRole("button", { name: "cURL", exact: true }).click();
    const command = page.locator("textarea[readonly]");
    const existingRow = page.getByTestId(`execution-token-${existing.id}`);
    await expect(existingRow).toBeVisible();
    await expect(existingRow.getByTitle("Show token")).toHaveCount(0);
    await existingRow.click();
    await expect(command).toHaveValue(/Authorization: Bearer <your-execution-token>/);
    await expect(command).not.toHaveValue(/Bearer undefined/);

    const mintedResponse = page.waitForResponse((response) =>
      response.url().endsWith(endpoint) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "+ New Token", exact: true }).click();
    const minted = await (await mintedResponse).json() as { id: string; token: string };
    const mintedRow = page.getByTestId(`execution-token-${minted.id}`);
    await expect(command).toHaveValue(new RegExp(minted.token.replaceAll(".", "\\.")));
    await mintedRow.getByTitle("Show token").click();
    await expect(mintedRow).toContainText(minted.token);
    await page.getByRole("button", { name: "Copy cURL", exact: true }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(minted.token);

    await page.keyboard.press("Escape");
    await expect(command).toHaveCount(0);
    await page.getByRole("button", { name: "cURL", exact: true }).click();
    await expect(page.getByRole("button", { name: "+ New Token", exact: true })).toBeEnabled();
    await expect(command).toHaveValue(new RegExp(minted.token.replaceAll(".", "\\.")));

    const revokeResponse = page.waitForResponse((response) =>
      response.url().endsWith(`${endpoint}/${minted.id}`) && response.request().method() === "DELETE",
    );
    await mintedRow.getByTitle("Revoke token").click();
    await expectOk(await revokeResponse);
    await expect(command).toHaveValue(/Authorization: Bearer <your-execution-token>/);
    await expect(mintedRow.getByTitle("Show token")).toHaveCount(0);
    await expect(mintedRow).not.toContainText(minted.token);

    const anotherResponse = page.waitForResponse((response) =>
      response.url().endsWith(endpoint) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "+ New Token", exact: true }).click();
    const another = await (await anotherResponse).json() as { id: string; token: string };
    await expect(command).toHaveValue(new RegExp(another.token.replaceAll(".", "\\.")));
    await page.reload();
    await page.getByRole("button", { name: "cURL", exact: true }).click();
    const reloadedRow = page.getByTestId(`execution-token-${another.id}`);
    await expect(reloadedRow).toBeVisible();
    await expect(reloadedRow.getByTitle("Show token")).toHaveCount(0);
    await expect(command).toHaveValue(/Authorization: Bearer <your-execution-token>/);
    await expect(command).not.toHaveValue(/Bearer undefined/);
    await expect(command).not.toHaveValue(new RegExp(another.token.replaceAll(".", "\\.")));
    await expect(reloadedRow.getByTitle("Revoke token")).toBeEnabled();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
