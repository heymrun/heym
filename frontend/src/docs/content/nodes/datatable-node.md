# DataTable

The **DataTable** node reads, writes, and manages data in Heym DataTables. Use it for CRUD operations on first-party structured storage without external credentials.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.rows`, `$nodeLabel.row`, `$nodeLabel.success`, `$nodeLabel.id` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `dataTableId` | UUID | DataTable from [DataTable tab](../tabs/datatable-tab.md) |
| `dataTableOperation` | string | Operation: `find`, `getAll`, `count`, `getById`, `insert`, `update`, `remove`, `upsert` |
| `dataTableRowId` | expression | Row UUID (for getById, update, remove) |
| `dataTableData` | JSON string | Column values: `{"column_name": "value"}` |
| `dataTableFilter` | JSON string | Filter (find/upsert/count). `find` and `count` support operators `{"age": {"$gt": 18}}`; `upsert` uses exact-match `{"column_name": "value"}` |
| `dataTableSort` | string | Sort column, prefix `-` for descending |
| `dataTableLimit` | number | Max rows returned (default: 100) |

## Operations

| Operation | Required Fields | Description |
|-----------|----------------|-------------|
| `find` | dataTableId | Find rows matching an optional operator filter with optional sort/limit |
| `getAll` | dataTableId | Get all rows with optional sort/limit |
| `count` | dataTableId | Count rows matching an optional operator filter (counted in the database; returns just a number) |
| `getById` | dataTableId, dataTableRowId | Get a single row by UUID |
| `insert` | dataTableId, dataTableData | Insert a new row |
| `update` | dataTableId, dataTableRowId, dataTableData | Update row (merges data) |
| `remove` | dataTableId, dataTableRowId | Delete a row |
| `upsert` | dataTableId, dataTableFilter, dataTableData | Update if match found, insert otherwise |

## Example - Find Rows

```json
{
  "type": "dataTable",
  "data": {
    "label": "findActive",
    "dataTableId": "table-uuid",
    "dataTableOperation": "find",
    "dataTableFilter": "{\"status\": \"active\", \"age\": {\"$gte\": 18}, \"created_at\": {\"$contains\": \"2026-06\"}}",
    "dataTableSort": "-created_at",
    "dataTableLimit": 50
  }
}
```

## Example - Insert Row

```json
{
  "type": "dataTable",
  "data": {
    "label": "addUser",
    "dataTableId": "table-uuid",
    "dataTableOperation": "insert",
    "dataTableData": "{\"name\": \"$start.text\", \"status\": \"pending\"}"
  }
}
```

## Example - Count Rows

Count rows matching a condition in a single node, instead of `getAll` → If/Else → Map.

```json
{
  "type": "dataTable",
  "data": {
    "label": "activeAdults",
    "dataTableId": "table-uuid",
    "dataTableOperation": "count",
    "dataTableFilter": "{\"status\": \"active\", \"age\": {\"$gt\": 18}}"
  }
}
```

The result is available as `$activeAdults.count`. An empty or omitted filter counts every row.

### Find and count filter operators

In a `find` or `count` filter, a plain value means equals; an object value applies an operator:

| Operator | Meaning |
|----------|---------|
| `$eq` (or a plain value) | Equals |
| `$ne` | Not equals |
| `$gt`, `$gte`, `$lt`, `$lte` | Greater/less than comparisons (numeric for columns typed as `number`, otherwise text) |
| `$contains` | Case-insensitive substring match |
| `$in` | Value is in the given array |

Example combining several: `{"status": "active", "age": {"$gte": 18}, "plan": {"$in": ["pro", "team"]}, "name": {"$contains": "jo"}}`. Unknown operators are ignored. `upsert` filters still use exact-match values to find the row to update.

You can also filter on row metadata — `id`, `table_id`, `created_at`, `updated_at`, `created_by`, `updated_by` — which are stored as real columns rather than inside your data. For dates, pass a full value for range comparisons (e.g. `{"created_at": {"$gt": "2026-06-04"}}`) or use `$contains` for a partial text match (e.g. `{"created_at": {"$contains": "2026-06-04"}}`). If one of your own columns is named the same as a metadata field, the data column takes precedence.

## Output Access

- `$nodeLabel.success` - Boolean success status
- `$nodeLabel.rows` - Array of rows (find, getAll)
- `$nodeLabel.row` - Single row object (getById, insert, update, upsert)
- `$nodeLabel.row.data.column_name` - Access specific column value
- `$nodeLabel.count` - Number of rows (rows returned for find/getAll; matching-row total for count)
- `$nodeLabel.id` - Row UUID (insert, update, remove)
- `$nodeLabel.found` - Boolean (getById)
- `$nodeLabel.operation` - Operation name (e.g. `count`; `insert`/`update` for upsert)

## No Credential Required

Unlike external integrations, DataTable operates on Heym's internal database. The workflow owner's access permissions are checked automatically.

## Built by the AI Assistant

When the [AI Assistant](../reference/ai-assistant.md#data-tables) or [Chat](../tabs/chat-tab.md) builds this node, it picks or creates the table with you and writes the table's exact column names into `dataTableData` and `dataTableFilter`.

## Related

- [DataTable Tab](../tabs/datatable-tab.md) - Create and manage tables
- [Grist Node](./grist-node.md) - External spreadsheet integration
- [Expression DSL](../reference/expression-dsl.md) - Expression syntax for dynamic values
