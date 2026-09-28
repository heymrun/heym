import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClarifyAnswer, ClarifyOption, ClarifyQuestion } from "@/types/clarify";
import type { DataTable } from "@/types/dataTable";

import { selectedTableOption, useClarifyDataTables } from "@/composables/useClarifyDataTables";
import { dataTablesApi } from "@/services/api";

vi.mock("@/services/api", () => ({
  dataTablesApi: { get: vi.fn(), create: vi.fn() },
}));

const TABLE_ID = "7d4f1c2a-9b3e-4f5a-8c6d-1e2f3a4b5c6d";
const PICK: ClarifyOption = { label: "leads_2025", table: { id: TABLE_ID } };
const CREATE: ClarifyOption = {
  label: "Create a new table",
  createTable: {
    name: "leads",
    description: "Website leads",
    columns: [{ name: "email", type: "string", unique: true }],
  },
};
const QUESTION: ClarifyQuestion = {
  id: "table",
  text: "Which table should the leads go to?",
  type: "single",
  options: [PICK, CREATE, { label: "Skip" }],
};

function answer(selected: string, question: ClarifyQuestion = QUESTION): ClarifyAnswer {
  return { id: question.id, text: question.text, selected: [selected], other: "", prefill: "" };
}

function table(id: string, name: string): DataTable {
  return {
    id,
    name,
    description: null,
    columns: [],
    owner_id: "owner",
    row_count: 0,
    created_at: "2026-09-28T00:00:00Z",
    updated_at: "2026-09-28T00:00:00Z",
  };
}

describe("selectedTableOption", () => {
  it("finds a selected table or createTable option on a single-choice question", () => {
    expect(selectedTableOption(QUESTION, answer("leads_2025"))).toBe(PICK);
    expect(selectedTableOption(QUESTION, answer("Create a new table"))).toBe(CREATE);
    expect(selectedTableOption(QUESTION, answer("Skip"))).toBeUndefined();
    expect(selectedTableOption({ ...QUESTION, type: "multi" }, answer("leads_2025"))).toBeUndefined();
  });
});

describe("useClarifyDataTables", () => {
  beforeEach(() => vi.clearAllMocks());

  it("creates the proposed table on submit and records it on the answer", async () => {
    vi.mocked(dataTablesApi.create).mockResolvedValue(table("t-new", "leads"));
    const tables = useClarifyDataTables();
    const state = { table: answer("Create a new table") };
    const onCreated = vi.fn();

    await expect(tables.prepare([QUESTION], state, onCreated)).resolves.toBe(true);

    const payload = vi.mocked(dataTablesApi.create).mock.calls[0][0];
    expect(payload.name).toBe("leads");
    expect(payload.description).toBe("Website leads");
    expect(payload.columns).toEqual([
      expect.objectContaining({ name: "email", type: "string", unique: true, required: false, order: 0 }),
    ]);
    expect(state.table.dataTable).toEqual({ id: "t-new", name: "leads" });
    expect(onCreated).toHaveBeenCalledWith(table("t-new", "leads"));
  });

  it("keeps the card open with the API's error when creation fails", async () => {
    vi.mocked(dataTablesApi.create).mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: "Data table with this name already exists" } },
    });
    const tables = useClarifyDataTables();
    const state = { table: answer("Create a new table") };

    await expect(tables.prepare([QUESTION], state, vi.fn())).resolves.toBe(false);

    expect(tables.errors.table).toBe("Data table with this name already exists");
    expect(state.table.dataTable).toBeUndefined();
    expect(tables.creating.value).toBe(false);
  });

  it("does not create a table twice when a retry follows a later failure", async () => {
    const second: ClarifyQuestion = { ...QUESTION, id: "archive", text: "Where do old leads go?" };
    vi.mocked(dataTablesApi.create)
      .mockResolvedValueOnce(table("t-new", "leads"))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(table("t-archive", "leads_archive"));
    const tables = useClarifyDataTables();
    const state = {
      table: answer("Create a new table"),
      archive: answer("Create a new table", second),
    };

    await expect(tables.prepare([QUESTION, second], state, vi.fn())).resolves.toBe(false);
    expect(tables.errors.archive).toBe("The table could not be created.");
    await expect(tables.prepare([QUESTION, second], state, vi.fn())).resolves.toBe(true);

    expect(dataTablesApi.create).toHaveBeenCalledTimes(3);
    expect(state.table.dataTable?.id).toBe("t-new");
    expect(state.archive.dataTable?.id).toBe("t-archive");
  });

  it("names a picked table the way the API does, once per table", async () => {
    vi.mocked(dataTablesApi.get).mockResolvedValue(table(TABLE_ID, "leads_2025"));
    const tables = useClarifyDataTables();
    const state = { table: answer("leads_2025") };

    tables.select(QUESTION, PICK);
    await expect(tables.prepare([QUESTION], state, vi.fn())).resolves.toBe(true);

    expect(state.table.dataTable).toEqual({ id: TABLE_ID, name: "leads_2025" });
    expect(tables.tableState(PICK)?.name).toBe("leads_2025");
    expect(dataTablesApi.get).toHaveBeenCalledTimes(1);
  });

  it("leaves a picked table that is not available out of the answer", async () => {
    vi.mocked(dataTablesApi.get).mockRejectedValue(new Error("Not found"));
    const tables = useClarifyDataTables();
    const state = { table: answer("leads_2025") };

    await tables.prepare([QUESTION], state, vi.fn());

    expect(state.table.dataTable).toBeUndefined();
    expect(tables.tableState(PICK)).toBeNull();
  });
});
