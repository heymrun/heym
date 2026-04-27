# SSE Streaming

Workflows can stream execution events in real time with Server-Sent Events (SSE).

## Endpoint

`POST /api/workflows/{workflow_id}/execute/stream`

This endpoint uses the same workflow-level authentication, rate limiting, and response caching rules as the standard execute endpoint documented in [Webhooks](./webhooks.md).

## Enabling SSE in the cURL Dialog

Open the **Run with cURL** dialog in the editor and enable **SSE Streaming**.

When enabled, Heym:

- switches the generated command from `/execute` to `/execute/stream`
- adds `--no-buffer` so streamed events appear immediately in terminal output
- adds `Accept: text/event-stream`
- lets you configure per-node `node_start` messages directly in the dialog

## Event Protocol

Each SSE frame is newline-delimited JSON prefixed with `data: `.

| Event type | When it is emitted | Key fields |
|------------|--------------------|------------|
| `execution_started` | Immediately after the request is accepted | `execution_id` |
| `node_start` | Right before a node begins execution | `node_id`, `node_label`, optional `message` |
| `node_retry` | When a node retries | `node_id`, `attempt`, `max_attempts` |
| `node_complete` | After a node finishes | `node_id`, `node_label`, `status`, `output`, `execution_time_ms` |
| `final_output` | When an Output node returns early | `node_label`, `output` |
| `execution_complete` | After the workflow ends | `status`, `outputs`, `execution_time_ms` |

## Per-Node Start Messages

The cURL dialog stores SSE settings on the workflow itself:

- **Send start** controls whether a `node_start` event includes a `message`
- **Start message** defaults to `[START] {nodeLabel}`
- clearing a custom message falls back to the default text
- `node_complete` is always emitted and always includes the node output

Example stored config:

```json
{
  "node-uuid-llm": {
    "send_start": true,
    "start_message": "[START] Draft reply"
  },
  "node-uuid-http": {
    "send_start": false,
    "start_message": null
  }
}
```

## cURL Example

```bash
curl -X POST --no-buffer \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer <your-access-token>" \
  "https://app.heym.ai/api/workflows/{workflow_id}/execute/stream" \
  -d '{"message":"Hello"}'
```

Sample event stream:

```text
data: {"type":"execution_started","execution_id":"..."}

data: {"type":"node_start","node_id":"...","node_label":"LLM","message":"[START] LLM"}

data: {"type":"node_complete","node_id":"...","node_label":"LLM","status":"success","output":{"text":"Hello world"},"execution_time_ms":312}

data: {"type":"execution_complete","status":"success","outputs":{"LLM":{"text":"Hello world"}},"execution_time_ms":315}
```

## Security Notes

- `anonymous`, `jwt`, and `header_auth` workflows behave the same as the regular webhook endpoint
- response caching still applies when `cache_ttl_seconds` is configured
- workflow rate limits still apply when `rate_limit_requests` and `rate_limit_window_seconds` are configured
- `test_run` bypasses both cache and rate limiting, the same way it does for `/execute`

## Related

- [Webhooks](./webhooks.md) – Standard execute endpoint and cURL dialog
- [Parallel Execution](./parallel-execution.md) – How streaming fits into Heym's DAG scheduler
- [Canvas Features](./canvas-features.md) – Editor controls including Run with cURL
- [Security](./security.md) – Authentication and secret handling
