# Dashboard

The **Dashboard** tab is a Grafana-style space where you build grids of chart widgets. Each widget is rendered from the output of its own hidden Heym workflow, so any data you can produce in a workflow — database queries, API calls, RAG lookups, LLM output — can become a chart. You can keep several dashboards and share each one with people or teams.

## Dashboards

Everyone starts with one dashboard, created the first time they open the tab. Use the dashboard selector at the top of the tab to switch between dashboards, and **+** next to it to create a new one. The selector lists your own dashboards first, then the ones shared with you, labelled with the name of the person who shared them.

The tab reopens the dashboard you used last, and the address bar carries the open dashboard (`?tab=dashboard&dashboard=<id>`), so a link opens that exact dashboard for anyone who has access to it.

The settings button (owners only) renames the dashboard, sets which records it accepts as a [detail page](#detail-pages), manages sharing, and deletes it. Deleting a dashboard removes its widgets and their workflows. You always keep at least one dashboard of your own, so the last one cannot be deleted.

## Widgets

A widget is a single chart on the grid. Supported chart types:

- **Bar** (vertical or horizontal)
- **Line**
- **Area** (filled trend, supports multiple series)
- **Pie**
- **Table** (scrollable; one column can render as [status chips](../nodes/chart-output-node.md#status-chips), and rows can open a [detail page](#detail-pages))
- **Numeric** (a single KPI value with an optional unit)
- **Gauge** (a single value against a min–max range, e.g. a percentage)
- **Scatter** (X/Y points for correlation plots)
- **Proportion** (one bar split into shares with a percentage legend, e.g. a language breakdown)
- **Bar gauge** (one horizontal gauge per row with a red→green gradient and a value, e.g. free disk space)
- **Text** (a markdown message, e.g. a status note like "Last execution at 19:47"; supports [interactive checkboxes](../nodes/chart-output-node.md#interactive-task-lists) when the markdown is static, and [explicit numbered lists](../nodes/chart-output-node.md#numbered-lists) for custom or descending numbering)
- **HITL** (your pending human reviews. The header shows `1/n pending`. The workflow name opens that run on the canvas. **Approve**, **Request changes**, and **Reject** resolve it. The history icon beside the widget title opens that run in the history dialog on this page. The widget does not use upstream rows, and each person sees their own queue)

Besides charts, a **Run a workflow** widget runs one of your workflows from the dashboard: on a dropped file, with its input fields, or with a Run button; see [Run widgets](#run-widgets).

Each widget loads its data asynchronously when you open the tab, so the page stays responsive while charts populate.

## Adding a widget

1. Click **Add widget**, give it a title, and pick a chart type. Below the picker, the dialog draws an example of that chart type with sample data and names the rows it expects, so you can compare types before you build anything.
2. The widget opens in the workflow editor with a starter graph: a [Set](../nodes/set-node.md) node that produces the rows, connected to a [Chart Output](../nodes/chart-output-node.md) node. Replace the Set node with any data source. A **HITL** widget is only the Chart Output node; it reads your pending reviews and does not need a data source.
3. Build the workflow so the node feeding **Chart Output** produces an array of rows, then configure the Chart Output node's field mapping (label field, value field, etc.).
4. Save, return to the Dashboard tab, and the widget renders.

For a **Run a workflow** widget, pick the workflow it runs instead; the picker says how the widget will run each one. The widget is added to the grid directly; there is no new workflow to build.

Double-click a widget (or use its edit button) to reopen its workflow at any time. Use **Clone
widget** in the widget header to duplicate both the widget and its complete workflow. The copy is
placed below the original and labeled with **(Copy)** so you can edit it independently.

## Detail pages

A table widget can link its rows to another dashboard, which then works as a detail page: one dashboard that serves every customer, invoice, or ticket.

1. Open the table widget's **Settings** and pick the dashboard under **Row link**.
2. Enter the **Record column**, the column whose value identifies the row (for example `id`), and optionally a **Label column** that names it (for example `name`).
3. Save. Clicking a row (or focusing it and pressing Enter) opens the linked dashboard with `?record=<value>&label=<name>`.

On the detail dashboard, every widget workflow reads the value as `$page.record` (see [Chart Output](../nodes/chart-output-node.md#detail-pages-pagerecord)), and the page shows `Dashboard / <label>` above the grid with a button to clear the record. Back returns to the table you came from.

- **Who can open it.** Rows are clickable only for viewers who can open the linked dashboard. Others see the same table without links.
- **Record format.** The record comes from the URL, so the detail dashboard decides what it accepts. In its settings, **Detail page records** is one of: IDs (letters, digits, `-`, `_` and `.`, up to 128 characters; the default), numbers, UUIDs, or email addresses. Any other value is refused before a widget runs, and the widgets show "This page does not accept that record".
- **Still the owner's run.** Widgets run as the dashboard owner on a detail page too. Builders should pass `$page.record` only where a node escapes it, never into query text.
- **Caching.** Each widget caches its chart per record, for the same time-to-live as the widget, and keeps the 50 most recently used records.

## Run widgets

A **Run a workflow** widget runs one of your workflows and shows the result: status, run time, and outputs. What it shows depends on what the workflow takes:

- **A file.** For a workflow that starts with a [File Upload Trigger](../nodes/file-upload-trigger-node.md), drop a file on it (or click to pick one) and the widget uploads it through the trigger's single-use upload link. The widget shows the file types and size the trigger accepts and refuses others before uploading.
- **Input fields.** For a workflow that starts with a Text Input node, the widget shows its fields with their defaults; **Run** runs the workflow with your values. Values for fields the workflow does not have are dropped.
- **Nothing.** A workflow without inputs gets a **Run** button.

- Anyone who can open the dashboard can run the widget, as anyone can refresh a chart. Access to the workflow is the dashboard owner's: adding the widget needs a workflow that both you and the owner can run, and the run itself uses the workflow owner's credentials, like any upload link.
- The result stays on your screen until you leave the page; other viewers do not see your files, values or results. The run appears in execution history with the trigger `dashboard`.
- A dashboard share never grants access to the workflow itself. **Edit workflow** opens it for people who already have access, and **Fine-tune with AI** is not offered.
- File runs execute on the main instance, where uploaded files are stored, as every File Upload Trigger run does.

## Generating a widget with AI

Click **AI**, describe the metric you want (for example, "workflow success rate over the last 30 days as a bar chart"), and pick an LLM credential and model. Heym generates a complete widget workflow ending in a Chart Output node and adds it to the grid. See [Chart Output](../nodes/chart-output-node.md#example-ai-prompts) for example prompts per chart type.

Use a widget's **Fine-tune with AI** button to revise an existing widget with a new instruction. Each AI fine-tune snapshots the previous workflow into the widget's **Edit History**, so you can review or roll back changes from the workflow editor.

## Editing the layout

Toggle **Edit** to enter edit mode, where you can drag widgets and resize them on a 12-column grid. Layout changes are saved automatically. Widget titles are editable inline from the widget header.

## Caching and refresh

Each widget caches its last computed data on the server for a configurable time-to-live (TTL). While the cache is fresh, reopening the dashboard serves the stored result instead of re-running the workflow. The cache is replaced in place every time the data is recomputed (one cache per widget, plus one per record on a [detail page](#detail-pages)), and it is automatically invalidated when you edit the widget's workflow.

Use a widget's **Refresh** button (or **Refresh** in the toolbar) to bypass the cache and recompute immediately.

## Sharing

Owners share a dashboard from its settings, with individual users (by email) or with any [team](teams-tab.md) they belong to. Each share is **Read** or **Write**; when someone has both a personal and a team share, the stronger one applies.

| Action | Owner | Write | Read |
|--------|:-----:|:-----:|:----:|
| View widgets, refresh them, use auto-refresh | ✓ | ✓ | ✓ |
| Open detail pages, run run widgets | ✓ | ✓ | ✓ |
| Add, clone, delete, rename and resize widgets; AI generate and fine-tune; tick checklist items | ✓ | ✓ | |
| Open a widget's workflow in the editor | ✓ | ✓ | |
| Rename or delete the dashboard, set its record format, manage sharing | ✓ | | |

**Widgets always run as the dashboard owner.** Whoever is looking, a widget uses the owner's credentials and global variables, and its runs appear in the owner's execution history and traces. Teammates therefore see the same data without access to the accounts behind it, and every viewer shares the one cached result per widget. Widgets that a write collaborator adds or clones belong to the owner as well.

Because of this, **Write** carries the same trust as sharing a workflow for editing: a collaborator with write access can change what runs with your credentials. Give it only to people you would let edit your workflows. A test run that a collaborator starts from the workflow editor uses their own credentials, as with any shared workflow; only the dashboard itself runs as the owner. **Read** grants no access to the widget workflows, and read-only viewers receive the chart itself but not the per-node execution details behind it.

Removing a share, or lowering it from write to read, takes effect immediately.

## Related

- [Chart Output node](../nodes/chart-output-node.md)
- [Analytics tab](analytics-tab.md) — built-in execution metrics (distinct from user-built dashboards)
