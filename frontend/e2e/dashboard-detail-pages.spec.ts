import { expect, test, type Page } from "@playwright/test";

import { expectOk, ownDashboardId, prepareAuthenticatedPage } from "./support";

interface Created {
  id: string;
  workflow_id: string;
}

async function createDashboard(page: Page, name: string): Promise<string> {
  const response = await page.request.post("/api/dashboards", { data: { name } });
  await expectOk(response);
  return ((await response.json()) as { id: string }).id;
}

async function deleteDashboard(page: Page, dashboardId: string): Promise<void> {
  const response = await page.request.delete(`/api/dashboards/${dashboardId}`);
  expect([204, 404]).toContain(response.status());
}

/** A widget whose hidden workflow is `nodes`/`edges`, saved like the editor saves it. */
async function createWidget(
  page: Page,
  dashboardId: string,
  title: string,
  chartType: string,
  nodes: Record<string, unknown>[],
  edges: Record<string, unknown>[],
): Promise<Created> {
  const response = await page.request.post(`/api/dashboards/${dashboardId}/widgets`, {
    data: { title, chart_type: chartType, layout: { x: 0, y: 0, w: 6, h: 4 } },
  });
  await expectOk(response);
  const widget = (await response.json()) as Created;
  await expectOk(
    await page.request.put(`/api/workflows/${widget.workflow_id}`, { data: { nodes, edges } }),
  );
  return widget;
}

const CUSTOMER_ROWS =
  '$array(dict(id="ACME-1", name="Acme", state="Paid"), ' +
  'dict(id="GLOBEX-2", name="Globex", state="Disputed"))';

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
  // The user's own default dashboard, so the ones a test creates can all be deleted.
  await ownDashboardId(page);
});

test("a table links its rows to a detail page that reads the record", async ({ page }) => {
  const stamp = Date.now();
  const listId = await createDashboard(page, `Customers ${stamp}`);
  const detailId = await createDashboard(page, `Customer ${stamp}`);

  try {
    await createWidget(
      page,
      listId,
      "Customers",
      "table",
      [
        {
          id: "rows",
          type: "set",
          position: { x: 0, y: 0 },
          data: { label: "rows", mappings: [{ key: "rows", value: CUSTOMER_ROWS }] },
        },
        {
          id: "chart",
          type: "chartOutput",
          position: { x: 300, y: 0 },
          data: {
            label: "customers",
            chartType: "table",
            dataPath: "rows",
            statusColumn: "state",
            statusTones: { Disputed: "failure" },
          },
        },
      ],
      [{ id: "e1", source: "rows", target: "chart" }],
    );
    await createWidget(
      page,
      detailId,
      "Notes",
      "text",
      [
        {
          id: "note",
          type: "set",
          position: { x: 0, y: 0 },
          data: { label: "note", mappings: [{ key: "text", value: "Customer $page.record" }] },
        },
        {
          id: "chart",
          type: "chartOutput",
          position: { x: 300, y: 0 },
          data: { label: "notes", chartType: "text", valueField: "text" },
        },
      ],
      [{ id: "e1", source: "note", target: "chart" }],
    );

    await page.goto(`/?tab=dashboard&dashboard=${listId}`);

    // The status column renders as chips: a default word and a configured tone. The
    // first widget run on a fresh server can take a while.
    await expect(page.locator('[data-tone="success"]', { hasText: "Paid" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator('[data-tone="failure"]', { hasText: "Disputed" })).toBeVisible();
    await expect(page.locator('tr[role="link"]')).toHaveCount(0);

    // Link the rows to the detail dashboard from the widget's settings.
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    const rowLink = page.getByTestId("widget-row-link");
    await rowLink.locator("select").selectOption(detailId);
    await rowLink.getByLabel("Record column").fill("id");
    await rowLink.getByLabel("Label column").fill("name");
    await page.getByRole("button", { name: "Save" }).click();

    await page.locator('tr[data-record="ACME-1"]').click();

    await expect(page).toHaveURL(new RegExp(`dashboard=${detailId}.*record=ACME-1.*label=Acme`));
    await expect(page.getByTestId("dashboard-record-bar")).toContainText("Acme");
    await expect(page.getByText("Customer ACME-1")).toBeVisible({ timeout: 30_000 });

    // Back returns to the list the row was opened from.
    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`dashboard=${listId}`));
    await expect(page.getByTestId("dashboard-record-bar")).toHaveCount(0);
    await expect(page.locator('tr[data-record="GLOBEX-2"]')).toBeVisible();
  } finally {
    await deleteDashboard(page, listId);
    await deleteDashboard(page, detailId);
  }
});

test("a record outside the page's format never reaches a widget", async ({ page }) => {
  const detailId = await createDashboard(page, `Strict customer ${Date.now()}`);

  try {
    await createWidget(page, detailId, "Notes", "text", [
      {
        id: "chart",
        type: "chartOutput",
        position: { x: 0, y: 0 },
        data: { label: "notes", chartType: "text", text: "Hello" },
      },
    ], []);

    await page.goto(`/?tab=dashboard&dashboard=${detailId}&record=${encodeURIComponent("a b")}`);

    await expect(page.getByText("This page does not accept that record")).toBeVisible();
  } finally {
    await deleteDashboard(page, detailId);
  }
});
