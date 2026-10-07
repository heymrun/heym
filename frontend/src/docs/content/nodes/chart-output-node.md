# Chart Output

The **Chart Output** node is the terminal node of a [dashboard widget](../tabs/dashboard-tab.md) workflow. It takes the rows produced by the upstream nodes and turns them into a standardized chart payload that the dashboard renders.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 0 (terminal) |
| Output | Standardized chart payload |

Place this node **last** in a dashboard-widget workflow. The node before it should produce an array of row objects, for example:

```json
[
  { "month": "Jan", "revenue": 120 },
  { "month": "Feb", "revenue": 150 }
]
```

When you only have example/sample data (no real source), produce these rows with a **Set** node using `$array(dict(...), dict(...))` — for example `$array(dict(month="Jan", revenue=120), dict(month="Feb", revenue=150))`. Do **not** use `${...}` or bare `{...}` object literals; Heym builds objects only with `dict(key=value)`.

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `chartType` | string | `pie`, `bar`, `line`, `area`, `table`, `numeric`, `gauge`, `scatter`, `proportion`, `barGauge`, `text`, or `hitl` |
| `orientation` | string | `vertical` or `horizontal` (bar charts only) |
| `dataPath` | string | Dot path to the rows array inside the upstream output (e.g. `data` or `result.items`). Leave empty to auto-detect. |
| `labelField` | string | Row key used as the category label (pie/bar/line) |
| `valueField` | string | Row key used as the numeric value (pie/bar/line/numeric/gauge) |
| `series` | array | Optional multi-series definition `[{ "name": "Sent", "field": "sent" }]` for bar/line (overrides `valueField`) |
| `columns` | array | Optional column list for `table` (defaults to the keys of the first row) |
| `statusColumn` | string | Optional `table` column rendered as colored [status chips](#status-chips). It must be one of the shown columns. |
| `statusTones` | object | Optional map from a status value to a tone (`success`, `attention`, `failure`, `waiting`, `neutral`) for values the defaults do not cover |
| `xField` / `yField` | string | Row keys for the X and Y numeric axes (scatter) |
| `min` / `max` | number | Numeric range for `gauge` (default `0` / `100`) |
| `unit` | string | Optional unit shown next to a `numeric` or `gauge` value |
| `text` | string | Markdown message for the `text` chart type. Leave empty and set `valueField` to render a dynamic message pulled from upstream data. |
| `title` | string | Optional chart title |

## Chart types

- **bar / line / area / pie** — categorical charts driven by `labelField` + `valueField` (or `series` for multi-series bar/line/area). `area` is a filled trend chart.
- **table** — raw rows rendered as a scrollable table using `columns`. One column can render as [status chips](#status-chips), and rows can open a [detail page](../tabs/dashboard-tab.md#detail-pages).
- **numeric** — a single KPI value from the first row, with an optional `unit`.
- **gauge** — a single value shown against a `min`–`max` range (e.g. a percentage). Uses `valueField`.
- **scatter** — X/Y points from `xField` and `yField` for correlation plots.
- **proportion** — a single horizontal bar split into shares with a percentage legend (e.g. a language breakdown). Uses `labelField` + `valueField`.
- **barGauge** — one horizontal gauge per row with a red→green gradient and a value (e.g. free disk space). Uses `labelField` + `valueField`, optional `unit` and `max` (defaults to the largest row value).
- **text** — a markdown message (e.g. a status note like "Last execution at 19:47"). Put the markdown in `text` for a static message, or leave `text` empty and set `valueField` to render a string produced upstream. Supports headings, bold/italic, [lists](../nodes/chart-output-node.md#interactive-task-lists), links, and inline code.
- **hitl** — a carousel of your pending human reviews. The header shows `1/n pending`; the left arrow is disabled on the first card and the right arrow on the last. The workflow name opens that run on the canvas. **Approve**, **Request changes**, and **Reject** resolve it, and the history icon beside the widget title opens that run in the history dialog on the same page. This chart type ignores upstream rows, so the widget workflow is only the Chart Output node. Each signed-in person sees the reviews on workflows they own.

### Interactive task lists

Use GitHub-flavored markdown task list syntax in the static `text` field:

```markdown
- [x] Option 1
- [ ] Option 2
- [ ] Option 3
```

On the [Dashboard](../tabs/dashboard-tab.md), checkboxes render as clickable controls (dark and light mode friendly). Toggling a checkbox updates the widget workflow's `text` field and persists across refreshes.

**Inline editing:** double-click a task item's label to edit it in place. Press Enter or click away to save; press Escape to cancel. Clear the label completely to remove that item from the list.

**Links in task items:** when a label contains a markdown link (`[title](url)`), clicking the link opens the URL without toggling the checkbox. Click elsewhere on the row to toggle.

**Static text only:** interactivity requires GFM task list syntax (`- [ ]` / `- [x]`). Plain dynamic status messages without task items stay read-only. When markdown comes from `valueField`, the first toggle copies it into the static `text` field so changes persist.

### Numbered lists

Text widgets render markdown with **explicit line numbers preserved**. Prefix each line with the number you want shown (e.g. `9.`, `8.`, `7.`). Heym does not renumber lines for you.

**Why explicit numbers?** Standard markdown ordered lists (`1.`, `2.`, `3.`) become HTML `<ol>` lists, which only count **up** from the first number. A list written as `9.` / `8.` / `7.` would display as `9`, `10`, `11` in a normal markdown renderer. Prefixing each line with the intended number avoids that.

**Descending lists (e.g. newest first):** build the markdown in a workflow loop and compute the display number per item:

```
${loop.total - loop.index}. [${item.title}](https://example.com/watch?v=${item.id})
```

Typical pattern:

1. Fetch or build an array of items (e.g. HTTP → `body.videos`).
2. [Loop](./loop-node.md) over the array; inside the body, use a [Variable](./variable-node.md) with `.add()` to append one numbered line per iteration.
3. After the loop's **done** branch, [Set](./set-node.md) `join("\n")` on the accumulated array (or equivalent) into a single markdown string.
4. Point **Chart Output** `valueField` at that string (or set static `text`).

Example line expression inside the loop (label `processVideos`, items with `title` and `id`):

```
$processVideos.total - $processVideos.index + ". [" + $processVideos.item.title + "](https://www.youtube.com/watch?v=" + $processVideos.item.id + ")"
```

Resulting markdown:

```markdown
9. [Latest video](https://www.youtube.com/watch?v=abc)
8. [Previous video](https://www.youtube.com/watch?v=def)
1. [Oldest video](https://www.youtube.com/watch?v=xyz)
```

For a simple ascending list starting at 1, either prefix each line (`1.`, `2.`, `3.`) or use a loop with `$loop.index + 1`. Use [bullet lists](#interactive-task-lists) (`- item`) when you do not need numbers.

## Status chips

A `table` can show one column as colored chips. Set **Status column** in the node's properties (or `statusColumn` in the DSL) to a column name. Each value gets one of five tones, and common words get one without configuration:

| Tone | Default words |
|------|---------------|
| `success` | success, successful, succeeded, done, complete, completed, approved, active, ok, paid, passed, healthy, resolved, won, delivered, published |
| `attention` | warning, attention, review, needs review, at risk, partial, degraded, overdue, unpaid, expiring |
| `failure` | failed, failure, error, errored, rejected, declined, blocked, lost, expired |
| `waiting` | pending, waiting, queued, running, in progress, processing, scheduled, draft, new, open |
| `neutral` | anything else |

Matching ignores case, `_` and `-`, so `IN_PROGRESS` and `in-progress` are both `waiting`. Add **Status tones** for other values; an entry overrides the default for that value:

```json
{
  "type": "chartOutput",
  "data": {
    "label": "invoices",
    "chartType": "table",
    "dataPath": "rows",
    "columns": ["invoice", "customer", "state"],
    "statusColumn": "state",
    "statusTones": { "Disputed": "failure" }
  }
}
```

The server resolves each value to its tone, so Heym and Heym Work show the same colors.

## Detail pages: `$page.record`

A dashboard opened with `?record=<value>` runs every widget workflow with that value as `$page.record`. A table row link opens such a page; see [Detail pages](../tabs/dashboard-tab.md#detail-pages). On the dashboard opened without a record, and in the expression dialog, `$page.record` is null. A node labelled `page` takes precedence over it.

Use it to fetch the one record the page is about, for example in an [HTTP](./http-node.md) node:

```
https://crm.example.com/api/customers?id=$page.record
```

The value comes from a URL that anyone can edit. The dashboard only accepts values in its record format (letters, digits, `-`, `_` and `.` by default), but treat it as untrusted input all the same: pass it where the node escapes values, such as an HTTP query parameter or a [DataTable](./datatable-node.md) or ClickHouse filter value, and never build query text by joining strings with it. Widgets still run as the dashboard owner, whoever opens the page.

## How data is resolved

1. If `dataPath` is set, the node follows that dot path into the upstream output.
2. Otherwise it looks for an array: a top-level list, a `data` array, or the first list-valued field.
3. For `table`, each row becomes a table row using `columns` (or the first row's keys). With `statusColumn`, the payload also carries the tone of each value in that column.
4. For `numeric` and `gauge`, the value comes from `valueField` on the first row (or the first numeric field).
5. For `scatter`, each row becomes an `[xField, yField]` point.
6. For `text`, the message is taken from `valueField` on the first row when set, otherwise from the static `text` config (otherwise the first string field of the first row).

## Example

```json
{
  "type": "chartOutput",
  "data": {
    "label": "revenueChart",
    "chartType": "bar",
    "orientation": "vertical",
    "dataPath": "data",
    "labelField": "month",
    "valueField": "revenue",
    "title": "Monthly revenue"
  }
}
```

Gauge (single value vs. a range):

```json
{
  "type": "chartOutput",
  "data": {
    "label": "cpuGauge",
    "chartType": "gauge",
    "dataPath": "rows",
    "valueField": "value",
    "min": 0,
    "max": 100,
    "unit": "%"
  }
}
```

Scatter (X/Y points):

```json
{
  "type": "chartOutput",
  "data": {
    "label": "correlation",
    "chartType": "scatter",
    "dataPath": "rows",
    "xField": "x",
    "yField": "y"
  }
}
```

Proportion (one bar split by share + percentage legend):

```json
{
  "type": "chartOutput",
  "data": {
    "label": "languages",
    "chartType": "proportion",
    "dataPath": "rows",
    "labelField": "name",
    "valueField": "value",
    "title": "Most Used Languages"
  }
}
```

Area (filled multi-series trend):

```json
{
  "type": "chartOutput",
  "data": {
    "label": "memCpu",
    "chartType": "area",
    "dataPath": "rows",
    "labelField": "time",
    "series": [
      { "name": "Memory", "field": "memory" },
      { "name": "CPU", "field": "cpu" }
    ],
    "title": "Memory / CPU"
  }
}
```

Bar gauge (per-row gradient gauge with values):

```json
{
  "type": "chartOutput",
  "data": {
    "label": "freeDisk",
    "chartType": "barGauge",
    "dataPath": "rows",
    "labelField": "name",
    "valueField": "value",
    "unit": "GB",
    "title": "Free disk space"
  }
}
```

Text (a static markdown message — no upstream rows required):

```json
{
  "type": "chartOutput",
  "data": {
    "label": "statusNote",
    "chartType": "text",
    "text": "**Last execution** at `19:47` — all checks passed ✅",
    "title": "Status"
  }
}
```

Text (dynamic — the message string is produced upstream and pulled via `valueField`):

```json
{
  "type": "chartOutput",
  "data": {
    "label": "lastRun",
    "chartType": "text",
    "dataPath": "rows",
    "valueField": "message"
  }
}
```

## Example AI prompts

When generating a widget with **AI**, prompts like these map cleanly to each type:

- **Bar** — "Show monthly revenue for the last 6 months as a vertical bar chart with example data."
- **Line** — "Plot daily active users over the last 14 days as a line chart."
- **Area** — "Show memory and CPU usage over the last 24 hours as an area chart with two series. Use example data."
- **Pie** — "Break down execution status (success, error, cancelled) as a pie chart."
- **Table** — "Show the top 10 workflows by execution count as a scrollable table with name and runs columns. Use example data."
- **Numeric** — "Show today's total workflow executions as a single KPI with unit 'runs'. Use example data."
- **Gauge** — "Show current CPU usage as a gauge from 0 to 100 percent."
- **Scatter** — "Plot request latency versus payload size as a scatter chart with example data."
- **Proportion** — "Show my most used languages as a proportion bar: Kotlin 49.64%, JavaScript 23.73%, TypeScript 11.64%, Java 8.92%, Python 6.06%. Use example data."
- **Bar gauge** — "Show free disk space per volume (sda1 to sda7) as a bar gauge in GB. Use example data."
- **Text** — "Add a text widget with a markdown checklist (one checked item, two unchecked), or list the 5 newest tutorial videos in descending order (5. down to 1.) with YouTube links — prefix each line with an explicit number (`5. Title`, `4. Title`, …)."

## Related

- [Dashboard tab](../tabs/dashboard-tab.md) — build and arrange widgets
- [Output node](output-node.md) — terminal node for regular workflows
