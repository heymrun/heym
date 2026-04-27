# Traces Tab

The **Traces** tab shows LLM execution traces. Inspect request/response payloads, timing, tool calls, and debug [Agent](../nodes/agent-node.md) and [LLM](../reference/node-types.md) node behavior.

<video src="/features/showcase/traces.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/traces.webm">▶ Watch Traces demo</a></p>

## Trace List

- Paginated list of recent traces
- Each trace shows: workflow, node, credential, timestamp, duration
- Click a trace to open the detail view
- Use **Prev / Next** inside the detail dialog to move between traces without closing it

## Filtering

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
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
