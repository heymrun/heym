import { expect, test, type Page } from "@playwright/test";

import {
  createWorkflow,
  deleteWorkflow,
  expectOk,
  ownDashboardId,
  prepareAuthenticatedPage,
} from "./support";

const PDF = { name: "march.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") };

async function createFileWorkflow(page: Page, name: string): Promise<string> {
  const workflow = await createWorkflow(
    page,
    name,
    [
      {
        id: "n1",
        type: "fileUploadTrigger",
        position: { x: 120, y: 120 },
        data: { label: "invoice", maxSizeMb: 5, allowedTypes: "application/pdf" },
      },
      {
        id: "n2",
        type: "output",
        position: { x: 420, y: 120 },
        data: { label: "Result", message: "Got $invoice.file.name" },
      },
    ],
    [{ id: "e1", source: "n1", target: "n2" }],
  );
  return workflow.id;
}

async function lastTriggerSource(page: Page, workflowId: string): Promise<string | null> {
  const response = await page.request.get(`/api/workflows/${workflowId}/history?limit=1`);
  await expectOk(response);
  const history = (await response.json()) as { items: { trigger_source: string | null }[] };
  return history.items[0]?.trigger_source ?? null;
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
  // The user's own default dashboard, so the one a test creates can be deleted.
  await ownDashboardId(page);
});

test("the Quick Drawer runs a File Upload workflow on a chosen file", async ({ page }) => {
  const name = `Invoice reader ${Date.now()}`;
  const workflowId = await createFileWorkflow(page, name);

  try {
    await page.goto("/");
    await page.getByRole("button", { name: "Open quick workflows drawer" }).click();
    // The home page lists the workflow too, behind the drawer; pick it in the drawer.
    const drawer = page.getByRole("complementary", { name: "Quick workflows drawer" });
    await drawer.getByPlaceholder("Filter workflows").fill(name);
    await drawer.getByRole("button").filter({ hasText: name }).first().click();

    const dropZone = page.getByTestId("file-drop-input");
    await expect(dropZone).toContainText("application/pdf, up to 5 MB");
    await expect(page.getByTestId("quick-workflow-run-start")).toBeDisabled();

    await dropZone.locator('input[type="file"]').setInputFiles(PDF);
    await expect(dropZone).toContainText("march.pdf");
    await page.getByTestId("quick-workflow-run-start").click();

    await expect(page.getByText("Got march.pdf").first()).toBeVisible({ timeout: 30_000 });
    expect(await lastTriggerSource(page, workflowId)).toBe("Quick Drawer");
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("a file-run widget runs its workflow on a dropped file", async ({ page }) => {
  const stamp = Date.now();
  const name = `Invoice reader ${stamp}`;
  const workflowId = await createFileWorkflow(page, name);
  const dashboardResponse = await page.request.post("/api/dashboards", {
    data: { name: `Invoices ${stamp}` },
  });
  await expectOk(dashboardResponse);
  const dashboardId = ((await dashboardResponse.json()) as { id: string }).id;

  try {
    await page.goto(`/?tab=dashboard&dashboard=${dashboardId}`);
    await page.getByTestId("dashboard-header").getByRole("button", { name: "Add widget" }).click();
    const dialog = page.getByTestId("add-widget-dialog");
    await dialog.getByTestId("add-widget-type").locator("select").selectOption("fileRun");
    await dialog.getByTestId("add-widget-file-workflow").locator("select").selectOption(workflowId);
    await dialog.getByRole("button", { name: "Add widget" }).click();

    const widget = page.getByTestId("file-run-widget");
    await expect(widget).toContainText("invoice");
    await widget.locator('input[type="file"]').setInputFiles(PDF);

    await expect(widget.getByText("Got march.pdf").first()).toBeVisible({ timeout: 30_000 });
    expect(await lastTriggerSource(page, workflowId)).toBe("dashboard");
  } finally {
    const removed = await page.request.delete(`/api/dashboards/${dashboardId}`);
    expect([204, 404]).toContain(removed.status());
    await deleteWorkflow(page, workflowId);
  }
});
