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

## LLM Cost Table (system table)

A pinned **System tables** section appears above your user-created tables with a single entry: **LLM Cost Table**. This is a fixed-schema, per-user editable view of per-model pricing used by the [Traces](./traces-tab.md) cost charts.

### Where the data comes from

Heym keeps a global table of per-model pricing seeded from Helicone's public pricing endpoint (`https://www.helicone.ai/api/llm-costs`). The sync runs in the background the first time you open the table or Traces and is throttled to one fetch per 24 hours. Press **Refresh** to force an immediate re-sync. Helicone removes from the upstream list are not deleted locally, so historic cost lookups stay stable.

### Schema (read-only columns)

| Column | Meaning |
|---|---|
| Provider | `ANTHROPIC`, `OPENAI`, `GOOGLE`, … (informational, used by Helicone) |
| Model | Model identifier matched against `trace.model` |
| Op | Match operator: `equals`, `startsWith`, or `includes` |
| Input $/1M | USD per 1 million prompt tokens |
| Output $/1M | USD per 1 million completion tokens |
| Source | `helicone`, `seed`, or `user` |

### Customizing pricing

- **Edit a row** to override its prices. Your override is per-user and is marked with a `Customized` badge; future Helicone syncs leave it alone.
- **Reset to default** removes the override and restores the global value for that row.
- **Add Custom Model** opens a dialog to create a user-only row (for example, a private fine-tuned model Helicone does not list). Custom rows are marked `User added` and deleting them removes them entirely.

### Matching against traces

When the Traces dashboard computes cost it matches each `trace.model` against:

1. Your overrides (exact match on model name) first
2. Otherwise the global table — `equals` exact match takes priority over `startsWith`/`includes`; ties within the same operator are resolved by longest matching model prefix/substring

If no row matches, the model is listed under the **Unpriced models** notice on the Traces page; its cost contribution is zero until you add a custom row or override one.

## Related

- [DataTable Node](../nodes/datatable-node.md) - Workflow node reference
- [Traces Tab](./traces-tab.md) - Uses the LLM Cost Table for the cost donut and KPI cards
- [Grist Node](../nodes/grist-node.md) - External spreadsheet alternative
- [Variables Tab](./global-variables-tab.md) - Key-value storage alternative
