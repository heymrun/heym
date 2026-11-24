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

test("the toolbar Refresh recomputes widgets instead of serving the cache", async ({ page }) => {
  const stamp = Date.now();
  const name = `refresh_note_${stamp}`;
  const created = await page.request.post("/api/global-variables", {
    data: { name, value: "first value" },
  });
  await expectOk(created);
  const variableId = ((await created.json()) as { id: string }).id;
  const dashboardId = await createDashboard(page, `Refresh ${stamp}`);

  try {
    await createWidget(
      page,
      dashboardId,
      "Note",
      "text",
      [
        {
          id: "note",
          type: "set",
          position: { x: 0, y: 0 },
          data: { label: "note", mappings: [{ key: "text", value: `$global.${name}` }] },
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

    await page.goto(`/?tab=dashboard&dashboard=${dashboardId}`);
    await expect(page.getByText("first value")).toBeVisible({ timeout: 20_000 });

    await expectOk(
      await page.request.patch(`/api/global-variables/${variableId}`, {
        data: { value: "second value" },
      }),
    );
    // The widget's result is cached for 300 s; the toolbar Refresh bypasses it, as the
    // widget's own Refresh does.
    await page.getByRole("button", { name: "Refresh dashboard" }).click();
    await expect(page.getByText("second value")).toBeVisible({ timeout: 20_000 });
  } finally {
    await deleteDashboard(page, dashboardId);
    await page.request.delete(`/api/global-variables/${variableId}`);
  }
});

test("auto-refresh keeps serving the cache, before and after a toolbar Refresh", async ({ page }) => {
  await page.clock.install();
  const stamp = Date.now();
  const name = `auto_note_${stamp}`;
  const created = await page.request.post("/api/global-variables", {
    data: { name, value: "first value" },
  });
  await expectOk(created);
  const variableId = ((await created.json()) as { id: string }).id;
  const setValue = async (value: string): Promise<void> => {
    await expectOk(
      await page.request.patch(`/api/global-variables/${variableId}`, { data: { value } }),
    );
  };
  const dashboardId = await createDashboard(page, `Auto refresh ${stamp}`);

  try {
    const widget = await createWidget(
      page,
      dashboardId,
      "Note",
      "text",
      [
        {
          id: "note",
          type: "set",
          position: { x: 0, y: 0 },
          data: { label: "note", mappings: [{ key: "text", value: `$global.${name}` }] },
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
    const dataLoad = (force: boolean) =>
      page.waitForResponse(
        (response) =>
          response.url().includes(`/api/dashboards/widgets/${widget.id}/data`) &&
          new URL(response.url()).searchParams.get("force") === String(force),
      );

    await page.goto(`/?tab=dashboard&dashboard=${dashboardId}`);
    await expect(page.getByText("first value")).toBeVisible({ timeout: 20_000 });

    // Auto-refresh every 60 s.
    await page.locator("div.w-28").getByRole("combobox").click();
    await page.getByRole("option", { name: "60s", exact: true }).click();

    // A timer refresh reloads the widget from its cache (TTL 300 s).
    await setValue("second value");
    let load = dataLoad(false);
    await page.clock.fastForward(61_000);
    await load;
    await expect(page.getByText("first value")).toBeVisible();

    // The toolbar Refresh skips the cache.
    load = dataLoad(true);
    await page.getByRole("button", { name: "Refresh dashboard" }).click();
    await load;
    await expect(page.getByText("second value")).toBeVisible();

    // The next timer refresh is back to the cache, so the forced load did not stick.
    await setValue("third value");
    load = dataLoad(false);
    await page.clock.fastForward(61_000);
    await load;
    await expect(page.getByText("second value")).toBeVisible();
  } finally {
    await deleteDashboard(page, dashboardId);
    await page.request.delete(`/api/global-variables/${variableId}`);
  }
});

test("dragging a widget saves the widgets it pushed aside", async ({ page }) => {
  const stamp = Date.now();
  const dashboardId = await createDashboard(page, `Layout ${stamp}`);
  const textWidget = async (title: string, layout: Record<string, number>): Promise<string> => {
    const widget = await createWidget(
      page,
      dashboardId,
      title,
      "text",
      [
        {
          id: "chart",
          type: "chartOutput",
          position: { x: 0, y: 0 },
          data: { label: "notes", chartType: "text", text: `${title} body` },
        },
      ],
      [],
    );
    await expectOk(await page.request.patch(`/api/dashboards/widgets/${widget.id}`, { data: { layout } }));
    return widget.id;
  };

  try {
    const alpha = await textWidget("Alpha", { x: 0, y: 0, w: 6, h: 4 });
    const beta = await textWidget("Beta", { x: 6, y: 0, w: 6, h: 4 });
    const gamma = await textWidget("Gamma", { x: 0, y: 4, w: 12, h: 4 });

    await page.goto(`/?tab=dashboard&dashboard=${dashboardId}`);
    await expect(page.getByText("Gamma body")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Edit dashboard" }).click();

    // Drag Gamma above Alpha and Beta; the grid pushes both down.
    // The three PATCHes go out together: Gamma, and Alpha and Beta that it pushed down.
    const saves = Promise.all(
      [alpha, beta, gamma].map((id) =>
        page.waitForResponse(
          (response) =>
            response.request().method() === "PATCH" &&
            response.url().endsWith(`/api/dashboards/widgets/${id}`),
        ),
      ),
    );
    const box = (await page.getByText("Gamma body").boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2, box.y - 260, { steps: 12 });
    await page.mouse.move(box.x + box.width / 2, box.y - 320, { steps: 12 });
    await page.mouse.up();
    await saves;

    const state = (await (await page.request.get(`/api/dashboards/${dashboardId}`)).json()) as {
      widgets: { id: string; layout: { x: number; y: number; w: number; h: number } }[];
    };
    const saved = Object.fromEntries(state.widgets.map((w) => [w.id, w.layout]));
    expect(saved[gamma].y).toBe(0);
    for (const id of [alpha, beta]) {
      // Each pushed widget is saved below Gamma, so nothing overlaps after a reload.
      expect(saved[id].y).toBeGreaterThanOrEqual(saved[gamma].y + saved[gamma].h);
    }

    await page.reload();
    await expect(page.getByText("Gamma body")).toBeVisible({ timeout: 20_000 });
    const gammaTop = (await page.getByText("Gamma body").boundingBox())!.y;
    const alphaTop = (await page.getByText("Alpha body").boundingBox())!.y;
    expect(gammaTop).toBeLessThan(alphaTop);
  } finally {
    await deleteDashboard(page, dashboardId);
  }
});

test("a task list with Windows line endings shows and toggles every checkbox", async ({ page }) => {
  const stamp = Date.now();
  const dashboardId = await createDashboard(page, `Checklist ${stamp}`);

  try {
    // Markdown from upstream with CRLF line endings, as a Windows file or some APIs send it.
    const widget = await createWidget(
      page,
      dashboardId,
      "Checklist",
      "text",
      [
        {
          id: "note",
          type: "set",
          position: { x: 0, y: 0 },
          data: {
            label: "note",
            mappings: [{ key: "text", value: "Release\r\n- [ ] Tag\r\n- [x] Notes\r\n- [ ] Ship" }],
          },
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

    await page.goto(`/?tab=dashboard&dashboard=${dashboardId}`);
    const boxes = page.getByRole("checkbox");
    await expect(boxes).toHaveCount(3, { timeout: 20_000 });
    await expect(boxes.nth(0)).toHaveAttribute("aria-checked", "false");
    await expect(boxes.nth(1)).toHaveAttribute("aria-checked", "true");

    const saved = page.waitForResponse((response) =>
      response.url().includes(`/api/dashboards/widgets/${widget.id}/markdown-task-toggle`),
    );
    await boxes.nth(0).click();
    expect((await saved).ok()).toBeTruthy();
    await expect(boxes.nth(0)).toHaveAttribute("aria-checked", "true");
  } finally {
    await deleteDashboard(page, dashboardId);
  }
});
