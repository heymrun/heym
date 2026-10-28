# Analytics Tab

The **Analytics** tab shows execution metrics and trends for your workflows. Monitor usage, performance, and identify bottlenecks.

<video src="/features/showcase/analytics.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/analytics.webm">▶ Watch Analytics demo</a></p>

## Summary Stats

- **Total executions** – Count of workflow runs in the selected period
- **Success rate** – Percentage of successful runs
- **Average duration** – Mean execution time
- **Time saved** – Total estimated time saved: each workflow's configured minutes-saved-per-run × its successful runs, summed across the selected window
- **Trends** – Up/down indicators vs previous period

## Time Range

- **24h** – Last 24 hours
- **7d** – Last 7 days
- **30d** – Last 30 days
- **All** – Entire available history

## Workflow Filter

- Filter metrics by a specific workflow
- **All workflows** – Aggregate across all workflows

## Tables

Two tables show workflow usage: **Most Used** (wider) and **Most Failed**.

- **Time Saved** – Most Used shows each workflow's summed time saved (minutes saved per run × successful runs). **Not Set** means the estimate is missing; click it to open that field on the workflow.
- **Sortable columns** – Click a column header to sort by that column. Click again to toggle ascending/descending. Arrow indicators show sort direction.
- **Mobile labels** – On small screens, column labels are shortened (e.g. "Executions" → "Runs", "Success" → "OK", "Error" → "Err") so the tables fit without horizontal scroll.

## Charts

- **Execution Volume Over Time** – Line chart of executions per time bucket
- **Success vs Error Rate** – Area chart comparing healthy and failed runs
- **Average Latency Over Time** – Line chart showing response-time changes
- **Drag to select** – Click and drag on any chart to focus a custom date range
- **Selection mode** – Selected ranges refresh the summary cards, charts, and workflow tables without changing the base preset
- **Clear Selection** – Return to the preset time window when you are done drilling in

## Node Types

Below the latency percentiles, three charts show where node time and failures go, grouped by node type (Agent, HTTP Request, Code, and so on) across the workflows in view:

- **Average Node Duration Over Time** – The 10 node types with the most total execution time, plotted as average duration per call. The header names the leader with its average and its total time.
- **Node Errors Over Time** – The 10 node types with the most errors (error or timeout), stacked per time bucket.
- **Node Calls Over Time** – The 10 node types that ran the most, stacked per time bucket. Skipped nodes are not counted.

The charts follow the workflow filter, the time range, and any range you drag on a chart. Node analytics are recorded for runs from the release that added them, and a finished run shows up within about a minute. Older runs are not counted.

## Auto Refresh

- Enable auto refresh to keep metrics updated without manual reload

## Related

- [Workflows Tab](./workflows-tab.md) – Workflows being measured
- [Traces Tab](./traces-tab.md) – Detailed trace inspection
- [Logs Tab](./logs-tab.md) – Runtime logs for debugging
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces

When a chart shows a trend you want to be told about rather than watch for, turn it into an [alert](./alerts-tab.md): error count, run duration, LLM spend, and execution count can all be given a threshold over a time window.
