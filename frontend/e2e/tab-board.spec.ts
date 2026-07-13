import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  createWorkflow,
  deleteAllBoards,
  deleteWorkflow,
  prepareAuthenticatedPage,
} from "./support";

// Board tests share one account's board list and assert on its empty state.
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
  await deleteAllBoards(page);
});

test.afterEach(async ({ page }) => {
  await deleteAllBoards(page);
});

const DEFAULT_COLUMNS = ["Backlog", "Planning", "Development", "Done"];

type ApiColumn = { id: string; name: string };
type ApiCard = { id: string; column_id: string; run_status: string };

/** The board dialogs require an Agentic Kanban Model, so the account needs a credential the
 *  API accepts as its own (the models come from the provider catalog, no provider call). */
async function setUpMapperCredential(page: Page): Promise<string> {
  const response = await page.request.post("/api/credentials", {
    data: { name: "Board model", type: "openai", config: { api_key: "sk-board-e2e" } },
  });
  const credential = await response.json();
  return credential.id;
}

/** Pick the credential and model in a board dialog. */
async function pickMapperModel(page: Page): Promise<void> {
  await page.getByPlaceholder("Credential", { exact: true }).click();
  await page.getByRole("option", { name: "Board model" }).click();
  await page.getByPlaceholder("Model", { exact: true }).click();
  await page.getByRole("option", { name: "GPT-4o", exact: true }).click();
}

/** Board actions are gated on the Agentic Kanban Model in the UI, so tests that need
 *  cards on the board set them up through the API. */
async function createBoardWithCard(
  page: Page,
  title: string,
): Promise<{ boardId: string; cardId: string; columns: ApiColumn[] }> {
  const board = await (await page.request.post("/api/boards", { data: { name: "Test" } })).json();
  const state = await (await page.request.get(`/api/boards/${board.id}`)).json();
  const columns: ApiColumn[] = state.columns;
  const backlog = columns.find((c) => c.name === "Backlog")!;
  const card = await (
    await page.request.post(`/api/boards/${board.id}/cards`, {
      data: { title, column_id: backlog.id },
    })
  ).json();
  return { boardId: board.id, cardId: card.id, columns };
}

/** Poll the board until the card settles, returning its final column and status. */
async function waitForCard(
  page: Page,
  boardId: string,
  cardId: string,
): Promise<{ column: string; status: string }> {
  let column = "";
  let status = "";
  for (let i = 0; i < 60; i += 1) {
    const s = await (await page.request.get(`/api/boards/${boardId}`)).json();
    const card = (s.cards as ApiCard[]).find((c) => c.id === cardId);
    const columns: ApiColumn[] = s.columns;
    column = columns.find((c) => c.id === card?.column_id)?.name ?? "";
    status = card?.run_status ?? "";
    if (status === "success" || status === "failed") break;
    await page.waitForTimeout(500);
  }
  return { column, status };
}

async function createSetOutputWorkflow(page: Page): Promise<{ id: string }> {
  return createWorkflow(
    page,
    `Board WF ${Date.now()}`,
    [
      {
        id: "s1",
        type: "set",
        position: { x: 100, y: 100 },
        data: { label: "greet", mappings: [{ key: "text", value: "ok" }] },
      },
      {
        id: "o1",
        type: "output",
        position: { x: 400, y: 100 },
        data: { label: "out", message: "$greet.text" },
      },
    ],
    [{ id: "e1", source: "s1", target: "o1" }],
  );
}

test("requires the model to create a board, then shows the default columns", async ({ page }) => {
  await setUpMapperCredential(page);
  await page.goto("/?tab=board");
  await expect(page.getByTestId("board-panel")).toBeVisible();

  await page.getByTestId("board-empty-create").click();
  await page.getByPlaceholder("Board name").fill("Launch board");
  // The Agentic Kanban Model is mandatory: a name alone is not enough.
  const create = page.getByRole("button", { name: "Create board" });
  await expect(create).toBeDisabled();

  await pickMapperModel(page);
  await expect(create).toBeEnabled();
  await create.click();

  for (const columnName of DEFAULT_COLUMNS) {
    await expect(page.getByTestId(`board-column-${columnName}`)).toBeVisible();
  }
  // "To Do" is no longer a default column.
  await expect(page.getByTestId("board-column-To Do")).toHaveCount(0);
  await expect(page.getByTestId("board-column-Backlog").getByPlaceholder("Add a card")).toBeEnabled();
});

test("blocks board actions until a board has its model", async ({ page }) => {
  // Boards created outside the dialog (here, through the API) can lack a model.
  const { boardId } = await createBoardWithCard(page, "gated");
  await page.goto(`/?tab=board&board=${boardId}`);

  const addCard = page
    .getByTestId("board-column-Backlog")
    .getByPlaceholder("Set the Agentic Kanban Model in board settings first");
  await expect(addCard).toBeDisabled();
});

test("reflects the selected board in the URL and deep-links to it", async ({ page }) => {
  await setUpMapperCredential(page);
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await page.getByPlaceholder("Board name").fill("URL board");
  await pickMapperModel(page);
  await page.getByRole("button", { name: "Create board" }).click();

  await expect(page.getByTestId("board-column-Backlog")).toBeVisible();
  await expect(page).toHaveURL(/[?&]board=[0-9a-f-]{36}/);
  const boardId = new URL(page.url()).searchParams.get("board");
  expect(boardId).toBeTruthy();

  await page.goto(`/?tab=board&board=${boardId}`);
  await expect(page.getByTestId("board-column-Backlog")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`board=${boardId}`));
});

test("edits a board name and description from the settings dialog", async ({ page }) => {
  await setUpMapperCredential(page);
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await page.getByPlaceholder("Board name").fill("Old name");
  await pickMapperModel(page);
  await page.getByRole("button", { name: "Create board" }).click();
  await expect(page.getByTestId("board-column-Backlog")).toBeVisible();
  await expect(page.getByTestId("board-description")).toHaveCount(0);

  await page.getByTestId("board-edit").click();
  await page.getByTestId("board-edit-name").fill("Launch board");
  await page.getByTestId("board-edit-description").fill("Everything shipping this quarter");
  await page.getByTestId("board-edit-save").click();

  await expect(page.getByTestId("board-description")).toHaveText(
    "Everything shipping this quarter",
  );
  await expect(page.getByPlaceholder("Select board")).toHaveValue("Launch board");
});

test("closes the new board dialog on Escape", async ({ page }) => {
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await expect(page.getByPlaceholder("Board name")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByPlaceholder("Board name")).not.toBeVisible();
});

test("clones and deletes a card from the hover actions", async ({ page }) => {
  const { boardId } = await createBoardWithCard(page, "Draft brief");
  await page.goto(`/?tab=board&board=${boardId}`);

  const backlog = page.getByTestId("board-column-Backlog");
  await expect(backlog.getByText("Draft brief")).toHaveCount(1);

  const card = backlog.locator("[data-board-card]").first();
  await card.hover();
  await card.locator('[data-testid^="board-card-clone-"]').click();
  await expect(backlog.getByText("Draft brief")).toHaveCount(2);

  page.once("dialog", (dialog) => dialog.accept());
  const firstCard = backlog.locator("[data-board-card]").first();
  await firstCard.hover();
  await firstCard.locator('[data-testid^="board-card-delete-"]').click();
  await expect(backlog.getByText("Draft brief")).toHaveCount(1);
});

test("runs a column workflow chain to completion when a card enters", async ({ page }) => {
  const wf = await createSetOutputWorkflow(page);
  try {
    const { boardId, cardId, columns } = await createBoardWithCard(page, "run me");
    const planning = columns.find((c) => c.name === "Planning")!;
    await page.request.patch(`/api/boards/${boardId}/columns/${planning.id}`, {
      data: { workflow_ids: [wf.id] },
    });
    await page.request.post(`/api/boards/${boardId}/cards/${cardId}/move`, {
      data: { to_column_id: planning.id },
    });

    const { status } = await waitForCard(page, boardId, cardId);
    expect(status).toBe("success");

    const detail = await (
      await page.request.get(`/api/boards/${boardId}/cards/${cardId}`)
    ).json();
    expect(detail.runs.length).toBeGreaterThanOrEqual(1);
    expect(detail.runs[0].status).toBe("success");
  } finally {
    await deleteAllBoards(page);
    await deleteWorkflow(page, wf.id);
  }
});

test("planning runs but waits there — it does not auto-advance", async ({ page }) => {
  const wf = await createSetOutputWorkflow(page);
  try {
    const { boardId, cardId, columns } = await createBoardWithCard(page, "plan me");
    const planning = columns.find((c) => c.name === "Planning")!;
    await page.request.patch(`/api/boards/${boardId}/columns/${planning.id}`, {
      data: { workflow_ids: [wf.id] },
    });
    await page.request.post(`/api/boards/${boardId}/cards/${cardId}/move`, {
      data: { to_column_id: planning.id },
    });

    const { column, status } = await waitForCard(page, boardId, cardId);
    expect(status).toBe("success");
    // The planning gate: the card stays put waiting for a human answer.
    expect(column).toBe("Planning");
  } finally {
    await deleteAllBoards(page);
    await deleteWorkflow(page, wf.id);
  }
});

test("cascades to the last column once past the planning gate", async ({ page }) => {
  const wf = await createSetOutputWorkflow(page);
  try {
    const { boardId, cardId, columns } = await createBoardWithCard(page, "flow me");
    // Chain on "Development" (index 2, past the gate). "Done" is empty and must be
    // passed through, so the card should end up there.
    const development = columns.find((c) => c.name === "Development")!;
    await page.request.patch(`/api/boards/${boardId}/columns/${development.id}`, {
      data: { workflow_ids: [wf.id] },
    });
    await page.request.post(`/api/boards/${boardId}/cards/${cardId}/move`, {
      data: { to_column_id: development.id },
    });

    const { column, status } = await waitForCard(page, boardId, cardId);
    expect(status).toBe("success");
    expect(column).toBe("Done");
  } finally {
    await deleteAllBoards(page);
    await deleteWorkflow(page, wf.id);
  }
});

test("opens card detail, saves the description and posts a comment", async ({ page }) => {
  const { boardId } = await createBoardWithCard(page, "Plan the beta");
  await page.goto(`/?tab=board&board=${boardId}`);

  const backlog = page.getByTestId("board-column-Backlog");
  await backlog.getByText("Plan the beta").click();

  // Saving the description confirms and updates the board card.
  await page.getByPlaceholder("Describe the job for this card").fill("Ship the beta plan");
  await page.getByTestId("card-description-save").click();
  await expect(page.getByTestId("card-description-saved")).toBeVisible();

  await page.getByTestId("card-comment-input").fill("Focus on developer onboarding");
  await page.getByTestId("card-comment-submit").click();
  await expect(page.getByText("Focus on developer onboarding")).toBeVisible();
});

test("attaches a file to a card and removes it", async ({ page }) => {
  const { boardId } = await createBoardWithCard(page, "Needs a brief");
  await page.goto(`/?tab=board&board=${boardId}`);
  const card = page.getByTestId("board-column-Backlog").getByText("Needs a brief");
  await card.click();

  await page.getByTestId("card-attachment-input").setInputFiles({
    name: "brief.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("launch brief"),
  });

  const attachment = page.getByTestId("card-attachment-brief.txt");
  await expect(attachment).toBeVisible();

  // The canvas card shows a paperclip with the attachment count.
  await page.keyboard.press("Escape");
  const badge = page.locator("[data-testid^='board-card-attachments-']");
  await expect(badge).toHaveText("1");

  await card.click();
  await attachment.getByRole("button", { name: "Remove brief.txt" }).click();
  await expect(page.getByTestId("card-attachment-brief.txt")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-testid^='board-card-attachments-']")).toHaveCount(0);
});

test("attaches a file dropped on the card's dropzone", async ({ page }) => {
  const { boardId } = await createBoardWithCard(page, "Drop a brief");
  await page.goto(`/?tab=board&board=${boardId}`);
  await page.getByText("Drop a brief").click();

  // Build a DataTransfer in the page and drop it on the zone.
  const dataTransfer = await page.evaluateHandle(() => {
    const transfer = new DataTransfer();
    transfer.items.add(new File(["dropped brief"], "dropped.txt", { type: "text/plain" }));
    return transfer;
  });
  await page.getByTestId("card-attachment-dropzone").dispatchEvent("drop", { dataTransfer });

  await expect(page.getByTestId("card-attachment-dropped.txt")).toBeVisible();
});

test("shares a board with a user from the settings dialog", async ({ page, playwright }) => {
  await setUpMapperCredential(page);
  await page.goto("/?tab=board");
  await page.getByTestId("board-empty-create").click();
  await page.getByPlaceholder("Board name").fill("Shared board");
  await pickMapperModel(page);
  await page.getByRole("button", { name: "Create board" }).click();
  await expect(page.getByTestId("board-column-Backlog")).toBeVisible();

  // Share with a second account, then take the share back. The account is registered from
  // its own request context so the page keeps its own session.
  const email = `board-share-${Date.now()}@example.com`;
  const guest = await playwright.request.newContext({ baseURL: page.url() });
  const registered = await guest.post("/api/auth/register", {
    data: { email, password: "Password123!", name: "Share Target" },
  });
  expect(registered.ok()).toBeTruthy();
  await guest.dispose();

  await page.getByTestId("board-edit").click();
  await page.getByTestId("board-share-email").fill(email);
  await page.getByTestId("board-share-add").click();

  const share = page.getByTestId(`board-share-${email}`);
  await expect(share).toContainText("read");

  await share.getByRole("button", { name: `Remove ${email}` }).click();
  await expect(page.getByTestId(`board-share-${email}`)).toHaveCount(0);
});

test("deletes an activity from the card timeline", async ({ page }) => {
  const { boardId } = await createBoardWithCard(page, "Timeline card");
  await page.goto(`/?tab=board&board=${boardId}`);
  await page.getByText("Timeline card").click();

  await page.getByTestId("card-comment-input").fill("Drop this note");
  await page.getByTestId("card-comment-submit").click();
  const comment = page.getByText("Drop this note");
  await expect(comment).toBeVisible();

  const entry = page.locator("[data-testid^='activity-delete-']").first();
  await entry.click();

  await expect(page.getByText("Drop this note")).toHaveCount(0);
});

test("reorders columns by dragging a column header", async ({ page }) => {
  const { boardId } = await createBoardWithCard(page, "Stay put");
  await page.goto(`/?tab=board&board=${boardId}`);

  const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
  await page
    .getByTestId("board-column-handle-Done")
    .dispatchEvent("dragstart", { dataTransfer });
  await page
    .getByTestId("board-column-handle-Planning")
    .dispatchEvent("drop", { dataTransfer });

  const headers = page.locator("[data-testid^='board-column-handle-']");
  await expect(headers.nth(1)).toHaveAttribute("data-testid", "board-column-handle-Done");

  const state = await (await page.request.get(`/api/boards/${boardId}`)).json();
  expect((state.columns as ApiColumn[]).map((c) => c.name)).toEqual([
    "Backlog",
    "Done",
    "Planning",
    "Development",
  ]);
});
