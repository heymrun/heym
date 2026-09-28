import type { DataTable, DataTableListItem } from "@/types/dataTable";
import type { NodeData, WorkflowNode } from "@/types/workflow";

// Operations the executor refuses on a table shared read-only.
const WRITE_OPERATIONS = new Set(["insert", "update", "remove", "upsert"]);

/** A table the question card just created, in the shape the table list returns. */
export function dataTableListItemFrom(table: DataTable): DataTableListItem {
  return {
    id: table.id,
    name: table.name,
    description: table.description,
    column_count: table.columns.length,
    row_count: table.row_count,
    owner_id: table.owner_id,
    is_shared: false,
    shared_by: null,
    shared_by_team: null,
    permission: null,
    created_at: table.created_at,
    updated_at: table.updated_at,
  };
}

/**
 * The listed tables plus the ones question cards created. The server commits after it responds,
 * so a list loaded right after a create can miss the new table; keeping it separately means a
 * reload never drops it.
 */
export function withCreatedDataTables(
  listed: DataTableListItem[],
  created: DataTableListItem[],
): DataTableListItem[] {
  const ids = new Set(listed.map((table) => table.id));
  return [...listed, ...created.filter((table) => !ids.has(table.id))];
}

/** The listed table a generated value names (an id, or an exact name), or undefined. */
export function resolveDataTable(
  value: unknown,
  tables: DataTableListItem[],
): DataTableListItem | undefined {
  if (typeof value !== "string") return undefined;
  const text = value.trim();
  if (!text) return undefined;
  const byId = tables.find((table) => table.id.toLowerCase() === text.toLowerCase());
  if (byId) return byId;
  const named = tables.filter((table) => table.name === text);
  return named.find((table) => !table.is_shared) ?? (named.length === 1 ? named[0] : undefined);
}

function canWrite(table: DataTableListItem): boolean {
  return !table.is_shared || table.permission === "write";
}

/**
 * Keep only tables the user can reach in an AI-generated dataTable node, and never a read-only
 * table for an operation that writes. A value the node already had on the canvas stays as it
 * is: it was the user's own earlier choice.
 */
export function sanitizeGeneratedDataTableFields(
  node: WorkflowNode,
  tables: DataTableListItem[],
  existing: WorkflowNode | undefined,
): WorkflowNode {
  if (node.type !== "dataTable") return node;
  const data = { ...node.data } as unknown as Record<string, unknown>;
  const previous = (existing?.data ?? {}) as unknown as Record<string, unknown>;
  if (existing && previous.dataTableId === data.dataTableId) return node;
  const table = resolveDataTable(data.dataTableId, tables);
  const writes = WRITE_OPERATIONS.has(String(data.dataTableOperation ?? ""));
  data.dataTableId = table && (!writes || canWrite(table)) ? table.id : "";
  return { ...node, data: data as unknown as NodeData };
}
