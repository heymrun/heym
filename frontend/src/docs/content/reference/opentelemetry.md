# OpenTelemetry Tracing

Heym can emit [OpenTelemetry](https://opentelemetry.io/) traces for every workflow run, node execution, and Agent tool invocation. Each run produces a root span with child spans per node and Agent tool, so you can see which step failed, how long it took, what it called, and what came back. Spans are exported over OTLP/HTTP to any compatible backend such as Jaeger, Grafana Tempo, Honeycomb, Datadog, New Relic, or Grafana Cloud.

Tracing is **disabled by default**. When it is off there is no measurable overhead and no spans are created.

## Enabling Tracing

Set the following environment variables on the backend, then restart it:

For the complete environment variable list, see [Environment Variables](https://github.com/heymrun/heym/blob/main/ENVIRONMENT-VARIABLES.md).

| Variable | Default | Description |
|----------|---------|-------------|
| `HEYM_OTEL_ENABLED` | `false` | Master switch. Set to `true` to turn tracing on. |
| `HEYM_OTEL_EXPORTER_OTLP_ENDPOINT` | `""` | OTLP/HTTP base endpoint, for example `http://collector:4318`. Heym posts spans to `<endpoint>/v1/traces`. |
| `HEYM_OTEL_EXPORTER_OTLP_HEADERS` | `""` | Comma-separated `key=value` headers for exporter auth, for example `authorization=Bearer <token>`. |
| `HEYM_OTEL_SERVICE_NAME` | `heym` | The `service.name` resource attribute. |
| `HEYM_OTEL_TRACES_SAMPLER_RATIO` | `1.0` | Head sampling ratio between `0.0` and `1.0`, applied with a parent-based sampler. |
| `HEYM_OTEL_CAPTURE_NODE_IO` | `false` | When `true`, attach truncated node input and output payloads to node spans. Off by default for privacy. |

Minimal example:

```bash
HEYM_OTEL_ENABLED=true
HEYM_OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

You can confirm the active configuration in the app under **Settings → Observability** (open it from the gear icon in the header). That panel is read-only and never displays exporter secrets.

## What Gets Traced

### Workflow root span

Name: `heym.workflow.execute`

| Attribute | Description |
|-----------|-------------|
| `heym.workflow.id` | The workflow UUID. |
| `heym.node.count` | Number of nodes in the workflow. |
| `heym.workflow.test_mode` | `true` for test runs. |
| `heym.sub_workflow.depth` | Nesting depth when invoked as a sub-workflow. |
| `heym.workflow.status` | Final status of the run. A failed run sets the span status to `ERROR`. |

### Node span

Name: `heym.node.execute`, created as a child of the workflow span.

| Attribute | Description |
|-----------|-------------|
| `heym.node.id` | The node id. |
| `heym.node.type` | The node type, for example `agent`, `llm`, `http`. |
| `heym.node.label` | The node label shown on the canvas. |
| `heym.node.status` | `success` or `error`. Errors set the span status to `ERROR`. |
| `heym.node.duration_ms` | Node execution time in milliseconds. |
| `heym.llm.model` | Model name for LLM and agent nodes, when available. |
| `heym.llm.prompt_tokens` / `heym.llm.completion_tokens` / `heym.llm.total_tokens` | Token usage for LLM and agent nodes, when available. |

Node spans nest correctly under the workflow span even when nodes run in parallel, because the workflow context is propagated into worker threads.

### Agent tool span

Name: `heym.agent.tool.execute`, created under the active Agent node span.

| Attribute | Description |
|-----------|-------------|
| `heym.agent.tool.name` | Tool name selected by the model. |
| `heym.agent.tool.call_id` | Provider tool-call id, when available. |
| `heym.agent.tool.source` | Tool source such as `node_tool`, `mcp`, `skill`, or `sub_workflow`. |
| `heym.agent.tool.mcp_server` | MCP server label, when applicable. |
| `heym.agent.tool.iteration` | Agent tool-loop iteration. |
| `heym.agent.tool.args_bytes` | UTF-8 size of serialized tool arguments. |
| `heym.agent.tool.result_bytes` | UTF-8 size of serialized tool result. |
| `heym.agent.tool.status` | `success`, `error`, `pending`, `timeout`, or `cancelled`. Tool errors set the span status to `ERROR`. |

Raw tool arguments and results are not attached to spans by default.

## Agent tool payload safety

Persisted Agent observability payloads are redacted and truncated in code (`4096` chars per string, depth `6`, `32768` total chars per LLM trace write). The total trace budget is divided across tool records so an early large result cannot hide the identity and lifecycle status of later calls. Bounded `_generated_files` download metadata is reserved separately from bulky skill output:

- LLM trace `request` / `response` tool sections, including `_hitl_pending` copies written to the trace store
- Agent result `tool_calls` records shown in execution history
- Live Debug panel tool-result events, which reuse the same bounded sanitized record

Live tool execution, model-bound tool messages, and the in-memory HITL resume state (`_hitl_pending.agent_state.messages` / `tool_arguments`) keep the original values so resume and exact-arg matching still work. Only stored observability copies are sanitized.

## Trace Context Propagation

Heym follows the [W3C Trace Context](https://www.w3.org/TR/trace-context/) standard so traces stay connected across service boundaries.

- **Inbound webhooks:** when an incoming request carries a `traceparent` header, the workflow run is recorded as a child of that trace. This links Heym runs to the upstream system that triggered them.
- **Outbound HTTP:** the HTTP node injects `traceparent` into requests it makes, so downstream services can continue the same trace.
- **Sub-workflows:** a sub-workflow run is parented to the node that invoked it, preserving the call hierarchy in one trace.

Triggers without an inbound context (such as Cron, IMAP, RabbitMQ, and WebSocket) start a fresh trace per run.

## Reliability

- A slow or unreachable collector never blocks workflow execution. Spans are batched and exported in the background.
- If tracing fails to initialize (for example, a bad endpoint), the backend logs the error and continues with tracing disabled rather than failing to start.
- OTLP auth headers are read from the environment only. They are never stored in the database and never returned by the status API.

## Related

- [Settings](./user-settings.md) – The Observability tab that shows tracing status
- [Environment Variables](https://github.com/heymrun/heym/blob/main/ENVIRONMENT-VARIABLES.md) – Full configuration reference
- [Triggers](./triggers.md) – How workflows start, including webhooks
- [Execution History](./execution-history.md) – Heym's built-in per-run history view
- [HTTP](../nodes/http-node.md) – The node that propagates trace context to downstream calls
