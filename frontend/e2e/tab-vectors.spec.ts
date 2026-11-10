import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

// Creating a vector store provisions a QDrant collection, which is not available
// in the E2E environment, so these tests cover the panel UI and create-dialog
// validation rather than an actual store lifecycle.

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows the vector stores empty state", async ({ page }) => {
  await page.goto("/?tab=vectorstores");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Vector Stores", exact: true })).toBeVisible();
  await expect(main.getByRole("heading", { name: "No vector stores yet" })).toBeVisible();
  await expect(main.getByText("Create a vector store to start using RAG in your workflows")).toBeVisible();
  await expect(main.getByRole("button", { name: "New Vector Store" })).toBeVisible();
});

test("opens the create dialog and guards submission without a credential", async ({ page }) => {
  await page.goto("/?tab=vectorstores");
  await page.getByRole("button", { name: "New Vector Store" }).click();

  // The dialog opens with a name field.
  await expect(page.getByRole("heading", { name: "New Vector Store" })).toBeVisible();
  await page.locator("#store-name").fill(`E2E Store ${Date.now()}`);

  // With no QDrant credential, the dialog surfaces the requirement and keeps the
  // Create button disabled.
  await expect(page.getByText("No QDrant credentials found.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create", exact: true })).toBeDisabled();

  // Cancel closes the dialog.
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("heading", { name: "New Vector Store" })).toBeHidden();
});

const STORE_ID = "11111111-1111-4111-8111-111111111111";
const store = {
  id: STORE_ID,
  name: "Call notes",
  description: null,
  collection_name: "call_notes",
  created_at: "2026-11-10T10:00:00Z",
  updated_at: "2026-11-10T10:00:00Z",
  is_shared: false,
  shared_by: null,
  stats: null,
  backend: "pgvector",
};

test("adds a plain-text file of any name and follows a background upload", async ({ page }) => {
  const uploads: string[] = [];
  let jobsListed = 0;
  let audioDone = false;

  await page.route("**/api/vector-stores", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [store] }) : route.fallback(),
  );
  await page.route(`**/api/vector-stores/${STORE_ID}/check-duplicates`, (route) =>
    route.fulfill({ json: { duplicates: [] } }),
  );
  await page.route(`**/api/vector-stores/${STORE_ID}/upload**`, async (route) => {
    const body = route.request().postDataBuffer()?.toString("latin1") ?? "";
    const name = /filename="([^"]+)"/.exec(body)?.[1] ?? "";
    uploads.push(name);
    const queued = name.endsWith(".mp3");
    await route.fulfill({
      json: queued
        ? { chunks_processed: 0, points_inserted: 0, status: "queued", job_id: "job-1" }
        : { chunks_processed: 1, points_inserted: 1, status: "done", job_id: null },
    });
  });
  await page.route(`**/api/vector-stores/${STORE_ID}/ingest-jobs`, (route) => {
    jobsListed += 1;
    if (jobsListed >= 2) audioDone = true;
    const jobs = audioDone
      ? []
      : [{ id: "job-1", filename: "call.mp3", file_size: 4, kind: "audio", status: "processing", error: null, created_at: "", updated_at: "" }];
    return route.fulfill({ json: { jobs, total: jobs.length } });
  });
  await page.route(`**/api/vector-stores/${STORE_ID}/items**`, (route) =>
    route.fulfill({
      json: audioDone
        ? { sources: [{ source: "call.mp3", file_size: 4, chunk_count: 2, items: [] }], total_items: 2 }
        : { sources: [], total_items: 0 },
    }),
  );

  await page.goto("/?tab=vectorstores");
  await page.getByTitle("Upload files").click();
  await expect(page.getByText(/audio \(mp3, wav, ogg, flac\)/)).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles([
    { name: "burak.akgun", mimeType: "", buffer: Buffer.from("4 rfc ve pr\n") },
    { name: "call.mp3", mimeType: "audio/mpeg", buffer: Buffer.from("ID3\u0000") },
  ]);
  await page.getByRole("button", { name: "Upload (2)" }).click();

  await expect(page.getByText(/1 file\(s\) are being read in the background/)).toBeVisible();
  expect(uploads).toEqual(["burak.akgun", "call.mp3"]);

  // The dialog's corner X is also named "Close".
  await page.getByRole("button", { name: "Close", exact: true }).first().click();
  await expect(page.getByLabel("Upload Files")).toBeHidden();
  await page.getByRole("heading", { name: "Call notes" }).click();
  // The first jobs listing says the audio is processing; the next one (4 s later) is empty,
  // which reloads the items and shows the new source.
  await expect(page.getByTestId("vector-store-ingest-jobs")).toContainText("Transcribing");
  await expect(page.getByText("(2 chunks)")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("vector-store-ingest-jobs")).toBeHidden();
});

test("dismisses a background upload that failed", async ({ page }) => {
  let dismissed = false;
  await page.route("**/api/vector-stores", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [store] }) : route.fallback(),
  );
  await page.route(`**/api/vector-stores/${STORE_ID}/items**`, (route) =>
    route.fulfill({ json: { sources: [], total_items: 0 } }),
  );
  await page.route(`**/api/vector-stores/${STORE_ID}/ingest-jobs/job-2`, (route) => {
    dismissed = true;
    return route.fulfill({ status: 204 });
  });
  await page.route(`**/api/vector-stores/${STORE_ID}/ingest-jobs`, (route) =>
    route.fulfill({
      json: {
        jobs: [{ id: "job-2", filename: "quiet.mp3", file_size: 4, kind: "audio", status: "failed", error: "No speech was found in quiet.mp3.", created_at: "", updated_at: "" }],
        total: 1,
      },
    }),
  );

  await page.goto("/?tab=vectorstores");
  await page.getByRole("heading", { name: "Call notes" }).click();
  const jobs = page.getByTestId("vector-store-ingest-jobs");
  await expect(jobs).toContainText("No speech was found in quiet.mp3.");
  await jobs.getByTitle("Dismiss").click();
  await expect(jobs).toBeHidden();
  expect(dismissed).toBe(true);
});
