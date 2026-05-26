# Traces Tab

The **Traces** tab shows LLM execution traces. Inspect request/response payloads, timing, tool calls, and debug [Agent](../nodes/agent-node.md) and [LLM](../reference/node-types.md) node behavior, plus aggregate metrics (calls, tokens, cost, latency, error rate) across any time window.

<video src="/features/showcase/traces.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/traces.webm">▶ Watch Traces demo</a></p>

## Stats Header

The page opens with a stats summary above the trace list, computed across the selected time range and other active filters:

- **KPI cards** – Total Calls, Total Tokens, Total Cost (USD), Avg Latency, Error %
- **Tokens by Model** – Donut chart of token volume per model
- **Cost by Model** – Donut chart of USD spend per model. Models without pricing show a "Configure pricing" link to the [LLM Cost Table](./datatable-tab.md#llm-cost-table-system-table)
- **Calls Over Time** – Stacked area chart of successful vs failed calls per bucket (5 min / 1 h / 6 h / 1 day, chosen automatically per range)
- **Unpriced models notice** – Appears below the charts when some traced models have no pricing row, linking to the LLM Cost Table

## Time Range

A single **Time range** selector at the top of the filter bar drives both the stats header and the trace list. Choices: Last 1 hour, Last 24 hours, Last 7 days (default), Last 30 days, All time. Changing the range resets pagination and reloads charts and list together.

## Trace List

- Paginated list of recent traces within the selected time range
- Each trace shows: workflow, node, credential, timestamp, duration
- Click a trace to open the detail view
- Use **Prev / Next** inside the detail dialog to move between traces without closing it

## Filtering

- **Time range** – 1h / 24h / 7d / 30d / All; filters charts and list together
- **Credential** – Filter by credential (API key) used
- **Source** – Filter by workflow or execution source
- **Search** – Search by model, workflow, credential, or node label
- **Refresh** – Reload the current page of traces

## Trace Detail

When you open a trace:

- **Request** – Full request payload sent to the LLM
- **Response** – Model response, including tool calls if any
- **Timing breakdown** – `llm_ms`, `tools_ms`, `mcp_list_ms` for performance analysis
- **Tool calls** – Tool name, arguments, result, and elapsed time
- **Skills included** – Skills passed to the model in the request
- **Go to Workflow** – Jump directly to the related workflow from the trace detail dialog

## Copy and Export

- Copy request or response JSON to clipboard
- Use for debugging or sharing with support

## Maintenance

- **Clear All** – Delete all saved traces after confirmation
- Pagination controls show the current visible range (for example `1-25 of 240`)

## Related

- [Why Heym](../getting-started/why-heym.md) – Built-in LLM observability vs other platforms
- [Agent Node](../nodes/agent-node.md) – Agent node with tool calling
- [Node Types](../reference/node-types.md) – LLM and Agent nodes
- [Credentials Tab](./credentials-tab.md) – Credentials used in traces
- [DataTable Tab](./datatable-tab.md) – Hosts the LLM Cost Table used by the cost chart
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
