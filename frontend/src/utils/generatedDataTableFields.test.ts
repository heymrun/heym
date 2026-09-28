import { describe, expect, it } from "vitest";

import type { DataTable, DataTableListItem } from "@/types/dataTable";
import type { WorkflowNode } from "@/types/workflow";

import {
  dataTableListItemFrom,
  resolveDataTable,
  sanitizeGeneratedDataTableFields,
  withCreatedDataTables,
} from "./generatedDataTableFields";

function listed(id: string, name: string, permission?: string): DataTableListItem {
  return {
    id,
    name,
    description: null,
    column_count: 2,
    row_count: 0,
    owner_id: "owner",
    is_shared: permission !== undefined,
    shared_by: permission ? "ops@x.com" : null,
    shared_by_team: null,
    permission: permission ?? null,
    created_at: "2026-09-28T00:00:00Z",
    updated_at: "2026-09-28T00:00:00Z",
  };
}

const LEADS = listed("11111111-1111-4111-8111-111111111111", "leads");
const ORDERS = listed("22222222-2222-4222-8222-222222222222", "orders", "read");
const TABLES = [LEADS, ORDERS];

function node(data: Record<string, unknown>): WorkflowNode {
  return {
    id: "save",
    type: "dataTable",
    position: { x: 0, y: 0 },
    data: { label: "saveLead", dataTableOperation: "insert", ...data },
  } as unknown as WorkflowNode;
}

function tableId(result: WorkflowNode): unknown {
  return (result.data as unknown as Record<string, unknown>).dataTableId;
}

function sanitize(n: WorkflowNode, existing?: WorkflowNode): WorkflowNode {
  return sanitizeGeneratedDataTableFields(n, TABLES, existing);
}

describe("resolveDataTable", () => {
  it("accepts a listed id in any case, or an exact name", () => {
    expect(resolveDataTable(LEADS.id.toUpperCase(), TABLES)).toBe(LEADS);
    expect(resolveDataTable(" leads ", TABLES)).toBe(LEADS);
  });

  it("prefers the user's own table when a shared one has the same name", () => {
    const twin = listed("33333333-3333-4333-8333-333333333333", "leads", "write");

    expect(resolveDataTable("leads", [twin, LEADS])).toBe(LEADS);
  });

  it("rejects placeholders and unknown values", () => {
    for (const value of ["datatable-uuid", "Leads", 42, ""]) {
      expect(resolveDataTable(value, TABLES)).toBeUndefined();
    }
  });
});

describe("sanitizeGeneratedDataTableFields", () => {
  it("keeps a listed id and rewrites an exact name", () => {
    expect(tableId(sanitize(node({ dataTableId: LEADS.id })))).toBe(LEADS.id);
    expect(tableId(sanitize(node({ dataTableId: "leads" })))).toBe(LEADS.id);
  });

  it("empties placeholders, and read-only tables for operations that write", () => {
    expect(tableId(sanitize(node({ dataTableId: "datatable-uuid" })))).toBe("");
    expect(tableId(sanitize(node({ dataTableId: ORDERS.id })))).toBe("");
    expect(tableId(sanitize(node({ dataTableId: ORDERS.id, dataTableOperation: "find" })))).toBe(ORDERS.id);
  });

  it("keeps a value the node already had on the canvas", () => {
    const gone = "44444444-4444-4444-8444-444444444444";

    expect(tableId(sanitize(node({ dataTableId: gone }), node({ dataTableId: gone })))).toBe(gone);
  });

  it("leaves other node types alone", () => {
    const http = { id: "h", type: "http", position: { x: 0, y: 0 }, data: { label: "call" } } as unknown as WorkflowNode;

    expect(sanitize(http)).toBe(http);
  });
});

describe("withCreatedDataTables", () => {
  const CREATED = listed("55555555-5555-4555-8555-555555555555", "leads_new");

  it("keeps a table the card created when a list load does not show it yet", () => {
    // The server commits after it responds, so a load right after the create can miss it.
    expect(withCreatedDataTables([LEADS], [CREATED])).toEqual([LEADS, CREATED]);
  });

  it("lists a table once when the load already shows it", () => {
    expect(withCreatedDataTables([LEADS, CREATED], [CREATED])).toEqual([LEADS, CREATED]);
  });
});

describe("dataTableListItemFrom", () => {
  it("lists a table the card created as the user's own", () => {
    const created: DataTable = {
      id: LEADS.id,
      name: "leads",
      description: null,
      columns: [],
      owner_id: "owner",
      row_count: 0,
      created_at: "c",
      updated_at: "u",
    };

    expect(dataTableListItemFrom(created)).toMatchObject({
      id: LEADS.id,
      name: "leads",
      is_shared: false,
      permission: null,
      column_count: 0,
    });
  });
});
