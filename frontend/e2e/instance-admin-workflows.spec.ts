import { expect, request, test, type Page } from "@playwright/test";

import { acceptNextDialog, createWorkflow, E2E_USER, expectOk, prepareAuthenticatedPage } from "./support";

async function signInAsAdmin(page: Page): Promise<void> {
  const admin = { email: "instance-admin@heym.example.com", password: "Playwright123", name: "Instance Admin" };
  const registration = await page.request.post("/api/auth/register", { data: admin });
  if (registration.status() === 400) {
    await expectOk(await page.request.post("/api/auth/login", { data: admin }));
  } else {
    await expectOk(registration);
  }
}

/** Other people's workflows sit under Heym Users, collapsed until these folders are opened. */
async function openAnotherUsersWorkflow(page: Page, workflowId: string): Promise<void> {
  await page.getByTestId("workflow-folder-header-heym-users").click();
  await page.getByTestId(`workflow-folder-header-heym-user:${E2E_USER.email.toLowerCase()}`).click();
  await page.getByTestId(`workflow-card-${workflowId}`).click();
}

test("instance admin opens, pauses, resumes, and deletes another user's workflow", async ({ page, baseURL }) => {
  await prepareAuthenticatedPage(page);
  await page.setViewportSize({ width: 1600, height: 1000 });
  const workflow = await createWorkflow(page, `Employee workflow ${Date.now()}`, [
    { id: "cron", type: "cron", position: { x: 0, y: 0 }, data: { label: "cron", cronExpression: "0 0 1 1 *", active: true } },
    { id: "wait", type: "wait", position: { x: 200, y: 0 }, data: { label: "wait", duration: 8000, active: true } },
    { id: "disabled-cron", type: "cron", position: { x: 0, y: 200 }, data: { label: "disabledCron", cronExpression: "0 1 1 1 *", active: false } },
  ], [{ id: "edge", source: "cron", target: "wait" }]);

  // The normal owner does not gain admin controls or admin-only endpoints.
  await page.goto("/");
  await page.getByTestId(`workflow-card-${workflow.id}`).click();
  await expect(page.getByTestId("workflow-admin-controls")).toHaveCount(0);
  expect((await page.request.post(`/api/workflows/${workflow.id}/pause-triggers`)).status()).toBe(403);
  expect((await page.request.post(`/api/workflows/${workflow.id}/resume-triggers`)).status()).toBe(403);

  const owner = await request.newContext({ baseURL, storageState: await page.context().storageState() });
  const stranger = await request.newContext({ baseURL });
  const strangerEmail = `stranger-${Date.now()}@heym.example.com`;
  await expectOk(await stranger.post("/api/auth/register", {
    data: { email: strangerEmail, password: "Playwright123", name: "Unrelated user" },
  }));
  expect((await stranger.get(`/api/workflows/${workflow.id}`)).status()).toBe(404);
  expect((await stranger.delete(`/api/workflows/${workflow.id}`)).status()).toBe(404);
  await stranger.dispose();

  await signInAsAdmin(page);

  try {
    const detail = await page.request.get(`/api/workflows/${workflow.id}`);
    await expectOk(detail);
    expect((await detail.json()).permission).toBe("write");
    await page.goto("/");
    await openAnotherUsersWorkflow(page, workflow.id);
    const controls = page.getByTestId("workflow-admin-controls");
    await expect(controls).toContainText(E2E_USER.email);
    await expect(controls.getByRole("button", { name: "Stop runs" })).toHaveCount(0);

    const schedules = await page.request.get("/api/schedules", {
      params: { start: "2026-12-31T00:00:00Z", end: "2027-01-02T00:00:00Z", include_shared: true },
    });
    await expectOk(schedules);
    expect((await schedules.json()).events.some((event: { workflow_id: string }) => event.workflow_id === workflow.id)).toBe(true);

    // Start a long run as the owner; deleting from another session must wait for it.
    const execution = owner.post(`/api/workflows/${workflow.id}/execute`, { data: { inputs: {} } });
    await expect.poll(async () => {
      const response = await page.request.get("/api/workflows/executions/active");
      return (await response.json()).some((run: { workflow_id: string }) => run.workflow_id === workflow.id);
    }).toBe(true);
    expect((await page.request.delete(`/api/workflows/${workflow.id}`)).status()).toBe(409);

    await acceptNextDialog(page, () => page.getByTestId("workflow-admin-pause").click(), /Pause automatic triggers/);
    await expect(page.getByTestId("workflow-admin-resume")).toBeVisible();
    await expect(page.getByTestId("workflow-admin-pause")).toHaveCount(0);
    await page.reload();
    await openAnotherUsersWorkflow(page, workflow.id);
    await expect(page.getByTestId("workflow-admin-resume")).toBeVisible();
    const paused = await page.request.get("/api/schedules", {
      params: { start: "2026-12-31T00:00:00Z", end: "2027-01-02T00:00:00Z", include_shared: true },
    });
    expect((await paused.json()).events.some((event: { workflow_id: string }) => event.workflow_id === workflow.id)).toBe(false);

    await acceptNextDialog(page, () => page.getByTestId("workflow-admin-resume").click(), /Resume automatic triggers/);
    await expect(page.getByTestId("workflow-admin-pause")).toBeVisible();
    const resumed = await page.request.get(`/api/workflows/${workflow.id}`);
    const resumedNodes = (await resumed.json()).nodes as { id: string; data: { active: boolean } }[];
    expect(resumedNodes.find((node) => node.id === "cron")?.data.active).toBe(true);
    expect(resumedNodes.find((node) => node.id === "disabled-cron")?.data.active).toBe(false);
    const resumedSchedules = await page.request.get("/api/schedules", {
      params: { start: "2026-12-31T00:00:00Z", end: "2027-01-02T00:00:00Z", include_shared: true },
    });
    expect((await resumedSchedules.json()).events.filter((event: { workflow_id: string }) => event.workflow_id === workflow.id)).toHaveLength(1);
    await acceptNextDialog(page, () => page.getByTestId("workflow-admin-pause").click(), /Pause automatic triggers/);
    await expect(page.getByTestId("workflow-admin-resume")).toBeVisible();
    const runResponse = await execution;
    await expectOk(runResponse);
    await expect.poll(async () => {
      const response = await owner.get(`/api/workflows/${workflow.id}/history`);
      return (await response.json()).items[0]?.status;
    }, { timeout: 15_000 }).toBe("success");
    // The worker's registry cleanup is asynchronous.
    await expect.poll(async () => (await page.request.delete(`/api/workflows/${workflow.id}`)).status(), { timeout: 15_000 }).toBe(204);
    expect((await owner.get(`/api/workflows/${workflow.id}`)).status()).toBe(404);
  } finally {
    await owner.delete(`/api/workflows/${workflow.id}`);
    await owner.dispose();
  }
});

test("admin trigger controls appear only when the workflow contains a Cron node", async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await signInAsAdmin(page);

  const scenarios = [
    { label: "Manual workflow", type: "textInput", active: true },
    { label: "Listening workflow", type: "heymTrigger", active: true },
    { label: "Paused event workflow", type: "heymTrigger", active: false },
  ];
  const workflows = [];
  const cronWorkflow = await createWorkflow(page, `Paused Cron ${Date.now()}`, [
    { id: "input", type: "textInput", position: { x: 0, y: 0 }, data: { label: "Manual entry" } },
    { id: "cron", type: "cron", position: { x: 0, y: 200 }, data: { label: "Paused schedule", cronExpression: "0 0 1 1 *", active: false } },
  ]);

  try {
    for (const scenario of scenarios) {
      const workflow = await createWorkflow(page, `${scenario.label} ${Date.now()}`, [
        { id: "entry", type: scenario.type, position: { x: 0, y: 0 }, data: { label: scenario.label, active: scenario.active } },
      ]);
      workflows.push({ ...workflow, label: scenario.label });
    }

    await page.goto("/");
    await page.getByTestId(`workflow-card-${cronWorkflow.id}`).click();
    await expect(page.getByTestId("workflow-admin-resume")).toBeVisible();

    // The previous selection's Cron must not expose controls while the next detail loads.
    let releaseDetail = (): void => {};
    const detailGate = new Promise<void>((resolve) => { releaseDetail = resolve; });
    await page.route(`**/api/workflows/${workflows[0].id}`, async (route) => {
      await detailGate;
      await route.continue();
    }, { times: 1 });
    try {
      await page.getByTestId(`workflow-card-${workflows[0].id}`).click();
      await expect(page.getByTestId("workflow-preview-title")).toHaveText(workflows[0].name);
      await expect(page.getByTestId("workflow-admin-pause")).toHaveCount(0);
      await expect(page.getByTestId("workflow-admin-resume")).toHaveCount(0);
    } finally {
      releaseDetail();
    }

    for (const workflow of workflows) {
      await page.getByTestId(`workflow-card-${workflow.id}`).click();
      await expect(page.getByTestId("workflow-preview-step-1")).toContainText(workflow.label);
      await expect(page.getByTestId("workflow-admin-controls")).toBeVisible();
      await expect(page.getByTestId("workflow-admin-pause")).toHaveCount(0);
      await expect(page.getByTestId("workflow-admin-resume")).toHaveCount(0);
    }
  } finally {
    for (const workflow of [cronWorkflow, ...workflows]) {
      await page.request.delete(`/api/workflows/${workflow.id}`);
    }
  }
});
