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
| `dataTableOperation` | string | Operation: `find`, `getAll`, `getById`, `insert`, `update`, `remove`, `upsert` |
| `dataTableRowId` | expression | Row UUID (for getById, update, remove) |
| `dataTableData` | JSON string | Column values: `{"column_name": "value"}` |
| `dataTableFilter` | JSON string | Exact-match filter: `{"column_name": "value"}` |
| `dataTableSort` | string | Sort column, prefix `-` for descending |
| `dataTableLimit` | number | Max rows returned (default: 100) |

## Operations

| Operation | Required Fields | Description |
|-----------|----------------|-------------|
| `find` | dataTableId | Find rows matching a filter with optional sort/limit |
| `getAll` | dataTableId | Get all rows with optional sort/limit |
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
    "dataTableFilter": "{\"status\": \"active\"}",
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

## Output Access

- `$nodeLabel.success` - Boolean success status
- `$nodeLabel.rows` - Array of rows (find, getAll)
- `$nodeLabel.row` - Single row object (getById, insert, update, upsert)
- `$nodeLabel.row.data.column_name` - Access specific column value
- `$nodeLabel.count` - Number of rows
- `$nodeLabel.id` - Row UUID (insert, update, remove)
- `$nodeLabel.found` - Boolean (getById)
- `$nodeLabel.operation` - "insert" or "update" (upsert)

## No Credential Required

Unlike external integrations, DataTable operates on Heym's internal database. The workflow owner's access permissions are checked automatically.

## Related

- [DataTable Tab](../tabs/datatable-tab.md) - Create and manage tables
- [Grist Node](./grist-node.md) - External spreadsheet integration
- [Expression DSL](../reference/expression-dsl.md) - Expression syntax for dynamic values
