# Dashboard

The **Dashboard** tab is a Grafana-style space where you build a grid of chart widgets. Each widget is rendered from the output of its own hidden Heym workflow, so any data you can produce in a workflow — database queries, API calls, RAG lookups, LLM output — can become a chart.

## Widgets

A widget is a single chart on the grid. Supported chart types:

- **Bar** (vertical or horizontal)
- **Line**
- **Area** (filled trend, supports multiple series)
- **Pie**
- **Table** (scrollable)
- **Numeric** (a single KPI value with an optional unit)
- **Gauge** (a single value against a min–max range, e.g. a percentage)
- **Scatter** (X/Y points for correlation plots)
- **Proportion** (one bar split into shares with a percentage legend, e.g. a language breakdown)
- **Bar gauge** (one horizontal gauge per row with a red→green gradient and a value, e.g. free disk space)
- **Text** (a markdown message, e.g. a status note like "Last execution at 19:47"; supports [interactive checkboxes](../nodes/chart-output-node.md#interactive-task-lists) when the markdown is static, and [explicit numbered lists](../nodes/chart-output-node.md#numbered-lists) for custom or descending numbering)

Each widget loads its data asynchronously when you open the tab, so the page stays responsive while charts populate.

## Adding a widget

1. Click **Add widget**, give it a title, and pick a chart type.
2. The widget opens in the workflow editor with a starter graph: an input node connected to a [Chart Output](../nodes/chart-output-node.md) node.
3. Build the workflow so the node feeding **Chart Output** produces an array of rows, then configure the Chart Output node's field mapping (label field, value field, etc.).
4. Save, return to the Dashboard tab, and the widget renders.

Double-click a widget (or use its edit button) to reopen its workflow at any time. Use **Clone
widget** in the widget header to duplicate both the widget and its complete workflow. The copy is
placed below the original and labeled with **(Copy)** so you can edit it independently.

## Generating a widget with AI

Click **AI**, describe the metric you want (for example, "workflow success rate over the last 30 days as a bar chart"), and pick an LLM credential and model. Heym generates a complete widget workflow ending in a Chart Output node and adds it to the grid. See [Chart Output](../nodes/chart-output-node.md#example-ai-prompts) for example prompts per chart type.

Use a widget's **Fine-tune with AI** button to revise an existing widget with a new instruction. Each AI fine-tune snapshots the previous workflow into the widget's **Edit History**, so you can review or roll back changes from the workflow editor.

## Editing the layout

Toggle **Edit** to enter edit mode, where you can drag widgets and resize them on a 12-column grid. Layout changes are saved automatically. Widget titles are editable inline from the widget header.

## Caching and refresh

Each widget caches its last computed data on the server for a configurable time-to-live (TTL). While the cache is fresh, reopening the dashboard serves the stored result instead of re-running the workflow. The cache is replaced in place every time the data is recomputed (one cache per widget), and it is automatically invalidated when you edit the widget's workflow.

Use a widget's **Refresh** button (or **Refresh** in the toolbar) to bypass the cache and recompute immediately.

## Related

- [Chart Output node](../nodes/chart-output-node.md)
- [Analytics tab](analytics-tab.md) — built-in execution metrics (distinct from user-built dashboards)
