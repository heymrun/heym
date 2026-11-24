import { expect, test } from "@playwright/test";

import { expectOk, ownDashboardId, prepareAuthenticatedPage } from "./support";

const backendUrl = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || "10106"}`;

test("routes an HTML widget click through HTTP and renders the reply in the same card", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await ownDashboardId(page);
  const dashboard = await page.request.post("/api/dashboards", { data: { name: "E2E HTML actions" } });
  await expectOk(dashboard);
  const { id: dashboardId } = await dashboard.json() as { id: string };
  const button = `<button id="change">Change color</button>
    <script>document.getElementById('change').onclick = () => heym.action('color_change', { color: 'blue', count: 2 });</script>`;

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
            label: "colorChanger", chartType: "html", html: `<p>Ready</p>${button}`,
          } },
          { id: "request", type: "http", position: { x: 300, y: 0 }, data: {
            label: "request", curl: `curl '${backendUrl}/api/health'`,
          } },
          { id: "reply", type: "chartOutput", position: { x: 600, y: 0 }, data: {
            label: "reply", chartType: "html",
            html: `<p>$colorChanger.message $colorChanger.data.color $colorChanger.data.count HTTP $request.status</p>${button}`,
          } },
        ],
        edges: [
          { id: "click", source: "card", sourceHandle: "action", target: "request" },
          { id: "result", source: "request", target: "reply" },
        ],
      },
    }));

    await page.goto(`/workflows/${widget.workflow_id}`);
    const htmlNode = page.locator('.vue-flow__node[data-id="card"]');
    const numericNode = page.locator('.vue-flow__node[data-id="numeric"]');
    await expect(htmlNode.locator('.vue-flow__handle.source[data-handleid="action"]')).toHaveCount(1);
    await expect(htmlNode.locator(".vue-flow__handle.source")).toHaveCount(1);
    await expect(numericNode).toBeAttached();
    await expect(numericNode.locator(".vue-flow__handle.source")).toHaveCount(0);

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
    await frame.getByRole("button", { name: "Change color" }).click();
    await expectOk(await secondRun);
    await page.reload();
    await expect(frame.getByText("Ready")).toBeVisible();
  } finally {
    await expectOk(await page.request.delete(`/api/dashboards/${dashboardId}`));
  }
});
