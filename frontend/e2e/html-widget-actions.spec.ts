import { expect, test } from "@playwright/test";

import { expectOk, ownDashboardId, prepareAuthenticatedPage } from "./support";

const backendUrl = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || "10106"}`;

test("routes widget messages through one Action connection and validates terminal HTML results", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await ownDashboardId(page);
  const dashboard = await page.request.post("/api/dashboards", { data: { name: "E2E HTML actions" } });
  await expectOk(dashboard);
  const { id: dashboardId } = await dashboard.json() as { id: string };
  const buttons = `<button id="change">Change color</button><button id="redraw">Redraw</button>
    <script>
    document.getElementById('change').onclick = () => heym.action('color_change', { color: 'blue', count: 2 });
    document.getElementById('redraw').onclick = () => heym.action('redraw', { count: 3 });
    </script>`;

  try {
    const created = await page.request.post(`/api/dashboards/${dashboardId}/widgets`, {
      data: { title: "E2E HTML action", chart_type: "html" },
    });
    await expectOk(created);
    const widget = await created.json() as { id: string; workflow_id: string };
    await expectOk(await page.request.put(`/api/workflows/${widget.workflow_id}`, {
      data: {
        nodes: [
          { id: "numeric", type: "chartOutput", position: { x: 0, y: 180 }, data: {
            label: "numeric", chartType: "numeric", active: false,
          } },
          { id: "card", type: "chartOutput", position: { x: 0, y: 0 }, data: {
            label: "colorChanger", chartType: "html", html: `<p>Ready</p>${buttons}`,
          } },
          { id: "typeSwitch", type: "switch", position: { x: 275, y: 0 }, data: {
            label: "typeSwitch", expression: "$colorChanger.message", cases: ["color_change", "redraw"],
          } },
          { id: "request", type: "http", position: { x: 560, y: 0 }, data: {
            label: "request", curl: `curl '${backendUrl}/api/health'`,
          } },
          { id: "reply", type: "chartOutput", position: { x: 835, y: 0 }, data: {
            label: "reply", chartType: "table",
            html: `<p>$colorChanger.message $colorChanger.data.color $colorChanger.data.count HTTP $request.status</p>${buttons}`,
          } },
          { id: "redrawPage", type: "chartOutput", position: { x: 560, y: 180 }, data: {
            label: "redrawPage", chartType: "html", html: `<p>Redrawn $colorChanger.data.count</p>${buttons}`,
          } },
          { id: "legacy", type: "set", position: { x: 1090, y: 0 }, data: { label: "legacy" } },
        ],
        edges: [
          { id: "click", source: "card", sourceHandle: "action", target: "typeSwitch" },
          { id: "change", source: "typeSwitch", sourceHandle: "case-0", target: "request" },
          { id: "redraw", source: "typeSwitch", sourceHandle: "case-1", target: "redrawPage" },
          { id: "result", source: "request", target: "reply" },
          { id: "legacy-action", source: "reply", sourceHandle: "action", target: "legacy" },
        ],
      },
    }));

    await page.goto(`/workflows/${widget.workflow_id}`);
    const htmlNode = page.locator('.vue-flow__node[data-id="card"]');
    const numericNode = page.locator('.vue-flow__node[data-id="numeric"]');
    const replyNode = page.locator('.vue-flow__node[data-id="reply"]');
    const redrawNode = page.locator('.vue-flow__node[data-id="redrawPage"]');
    await expect(htmlNode.locator('.vue-flow__handle.source[data-handleid="action"]')).toHaveCount(1);
    await expect(htmlNode.locator(".vue-flow__handle.source")).toHaveCount(1);
    await expect(numericNode).toBeAttached();
    await expect(numericNode.locator(".vue-flow__handle.source")).toHaveCount(0);
    await expect(redrawNode).toBeAttached();
    await expect(redrawNode.locator(".vue-flow__handle.source")).toHaveCount(0);
    const label = htmlNode.getByText("colorChanger", { exact: true });
    const title = await label.boundingBox();
    const badge = await htmlNode.getByText("Action", { exact: true }).boundingBox();
    expect(title && badge && title.x + title.width < badge.x).toBe(true);
    await expect(label).toHaveJSProperty("scrollWidth", await label.evaluate((element) => element.clientWidth));

    await replyNode.dblclick();
    const chartType = page.getByTestId("chart-output-type").locator("select");
    await expect(chartType).toHaveValue("table");
    await expect(page.getByText("Action results must use the HTML chart type.")).toBeVisible();
    await expect(chartType.locator('option[value="table"]')).toBeDisabled();
    await chartType.selectOption("html");
    await expect(replyNode.locator(".vue-flow__handle.source")).toHaveCount(0);
    await page.getByRole("button", { name: "Remove outgoing connections" }).click();
    const save = page.waitForResponse((res) => res.request().method() === "PUT" &&
      new URL(res.url()).pathname === `/api/workflows/${widget.workflow_id}`);
    await page.getByTestId("save-workflow-button").click();
    await expectOk(await save);

    const responsePath = `/api/dashboards/widgets/${widget.id}/action`;
    await page.goto(`/?tab=dashboard&dashboard=${dashboardId}`);
    const frame = page.frameLocator('[data-testid="chart-html-frame"]');
    await expect(frame.getByText("Ready")).toBeVisible();
    const run = page.waitForResponse((response) => new URL(response.url()).pathname === responsePath);
    await frame.getByRole("button", { name: "Change color" }).click();
    const response = await run;
    await expectOk(response);
    expect(response.request().postDataJSON()).toMatchObject({
      node_id: "card", message: "color_change", data: { color: "blue", count: 2 },
    });
    await expect(frame.getByText("color_change blue 2 HTTP 200")).toBeVisible();
    const secondRun = page.waitForResponse((res) => new URL(res.url()).pathname === responsePath);
    await frame.getByRole("button", { name: "Redraw" }).click();
    const redrawResponse = await secondRun;
    await expectOk(redrawResponse);
    expect(redrawResponse.request().postDataJSON()).toMatchObject({ node_id: "card", message: "redraw" });
    await expect(frame.getByText("Redrawn 3")).toBeVisible();
    await page.reload();
    await expect(frame.getByText("Ready")).toBeVisible();
  } finally {
    await expectOk(await page.request.delete(`/api/dashboards/${dashboardId}`));
  }
});
