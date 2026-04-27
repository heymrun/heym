# Analytics Tab

The **Analytics** tab shows execution metrics and trends for your workflows. Monitor usage, performance, and identify bottlenecks.

<video src="/features/showcase/analytics.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/analytics.webm">▶ Watch Analytics demo</a></p>

## Summary Stats

- **Total executions** – Count of workflow runs in the selected period
- **Success rate** – Percentage of successful runs
- **Average duration** – Mean execution time
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

Two tables show workflow usage: **Most Used** and **Most Failed**.

- **Sortable columns** – Click a column header to sort by that column. Click again to toggle ascending/descending. Arrow indicators show sort direction.
- **Mobile labels** – On small screens, column labels are shortened (e.g. "Executions" → "Runs", "Success %" → "OK%", "Avg Latency" → "Lat.") so the tables fit without horizontal scroll.

## Charts

- **Execution Volume Over Time** – Line chart of executions per time bucket
- **Success vs Error Rate** – Area chart comparing healthy and failed runs
- **Average Latency Over Time** – Line chart showing response-time changes
- **Drag to select** – Click and drag on any chart to focus a custom date range
- **Selection mode** – Selected ranges refresh the summary cards, charts, and workflow tables without changing the base preset
- **Clear Selection** – Return to the preset time window when you are done drilling in

## Auto Refresh

- Enable auto refresh to keep metrics updated without manual reload

## Related

- [Workflows Tab](./workflows-tab.md) – Workflows being measured
- [Traces Tab](./traces-tab.md) – Detailed trace inspection
- [Logs Tab](./logs-tab.md) – Runtime logs for debugging
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
