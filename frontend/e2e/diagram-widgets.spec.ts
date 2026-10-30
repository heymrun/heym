import { expect, test, type Locator } from "@playwright/test";

import { expectOk, ownDashboardId, prepareAuthenticatedPage } from "./support";

const CASES = [
  {
    type: "gantt", title: "Delivery plan", aria: "Task schedule with progress and dependencies", text: "Design",
    expression: '$array(dict(id="plan", label="Planning", start="2026-10-01", end="2026-10-03", progress=100), dict(id="design", label="Design", start="2026-10-03", end="2026-10-08", progress=80, dependencies=array("plan")), dict(id="backend", label="Backend implementation", start="2026-10-06", end="2026-10-20", progress=55, dependencies=array("design")), dict(id="frontend", label="Frontend implementation", start="2026-10-09", end="2026-10-23", progress=40, dependencies=array("design")), dict(id="test", label="Test", start="2026-10-23", end="2026-10-29", progress=10, dependencies=array("backend", "frontend")), dict(id="launch", label="Launch", start="2026-10-30", end="2026-11-01", dependencies=array("test")))',
  },
  {
    type: "erDiagram", title: "Database schema", aria: "Database entities, fields and relationships", text: "customer_id",
    expression: '$dict(entities=array(dict(id="customers", label="Customers", fields=array(dict(name="id", type="uuid", key="PK"), dict(name="name", type="varchar"), dict(name="email", type="varchar"))), dict(id="orders", label="Orders", fields=array(dict(name="id", type="uuid", key="PK"), dict(name="customer_id", type="uuid", key="FK"), dict(name="status", type="varchar"), dict(name="total", type="numeric"))), dict(id="items", label="Order items", fields=array(dict(name="id", type="uuid", key="PK"), dict(name="order_id", type="uuid", key="FK"), dict(name="product_id", type="uuid", key="FK"), dict(name="quantity", type="int"))), dict(id="products", label="Products", fields=array(dict(name="id", type="uuid", key="PK"), dict(name="name", type="varchar"), dict(name="price", type="numeric")))), relations=array(dict(source="customers", target="orders", sourceField="id", targetField="customer_id", label="places an order", cardinality="one-to-many"), dict(source="orders", target="items", sourceField="id", targetField="order_id", label="includes order items"), dict(source="products", target="items", sourceField="id", targetField="product_id", label="appears in order items")))',
  },
];

async function expectDiagramFits(diagram: Locator): Promise<void> {
  await expect.poll(async () => diagram.evaluate((element) => {
    const svg = element as SVGSVGElement;
    const host = svg.parentElement!;
    const bounds = svg.getBoundingClientRect();
    if (Math.abs(bounds.width - host.clientWidth) > 2 || Math.abs(bounds.height - host.clientHeight) > 2) return false;
    const content = svg.getBBox();
    const matrix = svg.getScreenCTM();
    if (!matrix) return false;
    const point = svg.createSVGPoint();
    point.x = content.x;
    point.y = content.y;
    const top = point.matrixTransform(matrix);
    point.x += content.width;
    point.y += content.height;
    const bottom = point.matrixTransform(matrix);
    return top.x >= bounds.left - 1 && top.y >= bounds.top - 1 && bottom.x <= bounds.right + 1 && bottom.y <= bounds.bottom + 1;
  })).toBe(true);
}

async function expectRelationshipCaptionsClear(diagram: Locator): Promise<void> {
  await expect.poll(async () => diagram.evaluate((svg) => {
    const cards = Array.from(svg.querySelectorAll("[data-diagram-entity]"), (node) => node.getBoundingClientRect());
    return Array.from(svg.querySelectorAll("[data-diagram-relation-label]")).every((node) => {
      const label = node.getBoundingClientRect();
      return cards.every((card) => label.right <= card.left || label.left >= card.right || label.bottom <= card.top || label.top >= card.bottom);
    });
  })).toBe(true);
}

test("Gantt and entity relationship widgets run and render on desktop and narrow dashboards", async ({ page }, testInfo) => {
  await prepareAuthenticatedPage(page);
  await ownDashboardId(page);
  const response = await page.request.post("/api/dashboards", { data: { name: `Diagram widgets ${Date.now()}` } });
  await expectOk(response);
  const dashboard = await response.json() as { id: string };
  const widgetIds: string[] = [];
  try {
    for (const example of CASES) {
      const created = await page.request.post(`/api/dashboards/${dashboard.id}/widgets`, {
        data: { title: example.title, chart_type: example.type, layout: { x: 0, y: 0, w: 6, h: 5 } },
      });
      await expectOk(created);
      const widget = await created.json() as { id: string; workflow_id: string };
      widgetIds.push(widget.id);
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
      await expectDiagramFits(diagram);
    }
    await expect(page.getByRole("img", { name: CASES[1].aria, exact: true })).toContainText("1 : N");
    await expectRelationshipCaptionsClear(page.getByRole("img", { name: CASES[1].aria, exact: true }));
    await page.screenshot({ path: testInfo.outputPath("diagrams-desktop.png"), fullPage: true });
    await page.getByRole("button", { name: "Add widget", exact: true }).click();
    const dialog = page.getByTestId("add-widget-dialog");
    for (const example of CASES) {
      await dialog.getByTestId("add-widget-type").locator("select").selectOption(example.type);
      await expect(dialog.getByRole("img", { name: example.aria, exact: true })).toBeVisible();
      await expectDiagramFits(dialog.getByRole("img", { name: example.aria, exact: true }));
      await page.screenshot({ path: testInfo.outputPath(`${example.type}-preview.png`), fullPage: true });
    }
    await page.screenshot({ path: testInfo.outputPath("entity-preview.png"), fullPage: true });
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expectOk(await page.request.patch(`/api/dashboards/widgets/${widgetIds[0]}`, { data: { layout: { x: 0, y: 0, w: 4, h: 7 } } }));
    await expectOk(await page.request.patch(`/api/dashboards/widgets/${widgetIds[1]}`, { data: { layout: { x: 4, y: 0, w: 8, h: 5 } } }));
    await page.reload();
    for (const example of CASES) await expectDiagramFits(page.getByRole("img", { name: example.aria, exact: true }));
    await page.screenshot({ path: testInfo.outputPath("diagrams-resized.png"), fullPage: true });
    await page.setViewportSize({ width: 900, height: 800 });
    for (const example of CASES) await expectDiagramFits(page.getByRole("img", { name: example.aria, exact: true }));
    await expectOk(await page.request.patch(`/api/dashboards/widgets/${widgetIds[0]}`, { data: { layout: { x: 0, y: 0, w: 12, h: 5 } } }));
    await expectOk(await page.request.patch(`/api/dashboards/widgets/${widgetIds[1]}`, { data: { layout: { x: 0, y: 5, w: 12, h: 5 } } }));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    for (const example of CASES) {
      await expect(page.getByRole("img", { name: example.aria, exact: true })).toBeVisible();
      await expectDiagramFits(page.getByRole("img", { name: example.aria, exact: true }));
    }
    await page.screenshot({ path: testInfo.outputPath("diagrams-mobile.png"), fullPage: true });
  } finally {
    await expectOk(await page.request.delete(`/api/dashboards/${dashboard.id}`));
  }
});
