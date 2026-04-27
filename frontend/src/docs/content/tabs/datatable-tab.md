# DataTable

The **DataTable** tab lets you create and manage structured data tables directly in Heym. Tables can be used in workflows via the [DataTable node](../nodes/datatable-node.md) for programmatic CRUD operations.

<video src="/features/showcase/datatable.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/datatable.webm">▶ Watch DataTable demo</a></p>

## Creating a Table

1. Navigate to the DataTable tab from the dashboard
2. Click **Create DataTable**
3. Enter a name and optional description
4. Add columns with the column editor

## Columns

Each column has:

| Property | Description |
|----------|-------------|
| Name | Column display name |
| Type | `string`, `number`, `boolean`, `date`, or `json` |
| Required | Whether new rows must include this column |
| Unique | Whether values must be unique across rows |
| Default Value | Auto-filled when a row omits this column |

Add, edit, or remove columns from the table detail view header.

## Managing Rows

- **Add row**: Click the add button to create a new row
- **Inline edit**: Double-click any cell to edit its value. Press Enter or click away to save, Escape to cancel
- **Delete row**: Use the row action menu to remove a row
- **Pagination**: Rows display 25 per page with page navigation

## CSV Import/Export

### Import
1. Click **Import CSV** in the table detail view
2. Select a CSV file to upload
3. Preview the first 5 rows and column mapping
4. Green columns are matched to existing table columns; yellow are unmatched
5. Click Import to bulk-insert rows

### Export
Click **Export CSV** to download all rows as a CSV file.

## Sharing

Share tables with other users or teams:

1. Open the share dialog from the table detail view
2. Add users by email with **read** or **write** permission
3. Add teams with **read** or **write** permission
4. Read-only users can view data; write users can modify rows

## Using in Workflows

The [DataTable node](../nodes/datatable-node.md) connects tables to workflows. Operations include find, getAll, getById, insert, update, remove, and upsert. No credentials are required.

## Related

- [DataTable Node](../nodes/datatable-node.md) - Workflow node reference
- [Grist Node](../nodes/grist-node.md) - External spreadsheet alternative
- [Variables Tab](./global-variables-tab.md) - Key-value storage alternative
