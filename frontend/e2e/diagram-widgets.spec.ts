import { expect, test } from "@playwright/test";

import { expectOk, ownDashboardId, prepareAuthenticatedPage } from "./support";

const CASES = [
  {
    type: "gantt", title: "Delivery plan", aria: "Task schedule with progress and dependencies", text: "Design",
    expression: '$array(dict(id="design", label="Design", start="2026-10-01", end="2026-10-05", progress=60), dict(id="build", label="Build", start="2026-10-05", end="2026-10-14", dependencies=array("design")))',
  },
  {
    type: "erDiagram", title: "Database schema", aria: "Database entities, fields and relationships", text: "customer_id",
    expression: '$dict(entities=array(dict(id="customers", label="Customers", fields=array(dict(name="id", type="uuid", key="PK"))), dict(id="orders", label="Orders", fields=array(dict(name="customer_id", type="uuid", key="FK")))), relations=array(dict(source="customers", target="orders", sourceField="id", targetField="customer_id", cardinality="one-to-many")))',
  },
];

test("Gantt and entity relationship widgets run and render on desktop and narrow dashboards", async ({ page }, testInfo) => {
  await prepareAuthenticatedPage(page);
  await ownDashboardId(page);
  const response = await page.request.post("/api/dashboards", { data: { name: `Diagram widgets ${Date.now()}` } });
  await expectOk(response);
  const dashboard = await response.json() as { id: string };
  try {
    for (const example of CASES) {
      const created = await page.request.post(`/api/dashboards/${dashboard.id}/widgets`, {
        data: { title: example.title, chart_type: example.type, layout: { x: 0, y: 0, w: 6, h: 5 } },
      });
      await expectOk(created);
      const widget = await created.json() as { workflow_id: string };
      await expectOk(await page.request.put(`/api/workflows/${widget.workflow_id}`, {
        data: {
          nodes: [
            { id: "data", type: "set", position: { x: 0, y: 0 }, data: { label: "data", mappings: [{ key: "data", value: example.expression }] } },
            { id: "chart", type: "chartOutput", position: { x: 300, y: 0 }, data: { label: "chart", chartType: example.type, dataPath: "data" } },
          ],
          edges: [{ id: "edge", source: "data", target: "chart" }],
        },
      }));
    }
    await page.goto(`/?tab=dashboard&dashboard=${dashboard.id}`);
    for (const example of CASES) {
      const diagram = page.getByRole("img", { name: example.aria, exact: true });
      await expect(diagram).toBeVisible();
      await expect(diagram).toContainText(example.text);
    }
    await expect(page.getByRole("img", { name: CASES[1].aria, exact: true })).toContainText("1 : N");
    await page.screenshot({ path: testInfo.outputPath("diagrams-desktop.png"), fullPage: true });
    await page.getByRole("button", { name: "Add widget", exact: true }).click();
    const dialog = page.getByTestId("add-widget-dialog");
    for (const example of CASES) {
      await dialog.getByTestId("add-widget-type").locator("select").selectOption(example.type);
      await expect(dialog.getByRole("img", { name: example.aria, exact: true })).toBeVisible();
    }
    await page.screenshot({ path: testInfo.outputPath("entity-preview.png"), fullPage: true });
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    for (const example of CASES) await expect(page.getByRole("img", { name: example.aria, exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("diagrams-mobile.png"), fullPage: true });
  } finally {
    await expectOk(await page.request.delete(`/api/dashboards/${dashboard.id}`));
  }
});
