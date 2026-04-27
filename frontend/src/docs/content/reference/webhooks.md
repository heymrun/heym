# Webhooks

Workflows can be triggered via HTTP webhooks. The standard execute endpoint returns JSON, and the streaming variant returns Server-Sent Events (SSE).

## Endpoint

`POST /api/workflows/{workflow_id}/execute`

Replace `{workflow_id}` with the workflow UUID. The base URL is your Heym instance (e.g. `https://app.heym.ai`).

## Streaming Endpoint

`POST /api/workflows/{workflow_id}/execute/stream`

Use the streaming endpoint when you want incremental execution events instead of a single JSON response. See [SSE Streaming](./sse-streaming.md) for the event protocol and per-node start message configuration.

## Request Format

The request body is passed as `body` to [Input](../nodes/input-node.md) nodes. Heym accepts both request shapes:

- **Raw JSON** – e.g. `{"userId": "123", "action": "create"}`
- **Wrapped format** – `{"inputs": {...}, "test_run": false}`

When using the wrapped format, `inputs` is extracted and passed as `body`. `test_run` bypasses rate limiting and response caching. You can also send `?test_run=true` as a query parameter when posting raw JSON.

## Request Body Modes

Each workflow has a `webhook_body_mode` setting that controls how the editor builds sample requests:

| Mode | Behavior |
|------|----------|
| **defined** | The editor and cURL dialog shape the example body from the workflow's Input node fields and keep empty keys in the JSON payload. Existing defined-style cURL payloads keep working. |
| **generic** | The editor and cURL dialog use a free-form JSON body. The request body is passed through as-is so external apps can send their own fixed payload shape. |

The execution API stays backward compatible in both modes. Raw JSON and wrapped `{ "inputs": ... }` requests are still accepted either way.

Headers and query params are available in expressions as `$input.headers` and `$input.query`. Header keys are lowercased.

## Authentication

Configure per workflow in the editor (workflow settings). Auth is checked before execution.

| auth_type | Behavior |
|-----------|----------|
| **anonymous** | No auth required. Anyone can call the endpoint. |
| **jwt** | Bearer token required. User must have workflow access. |
| **header_auth** | Custom header must match. Set `auth_header_key` (e.g. `X-API-Key`) and `auth_header_value`. |

For `header_auth`, the request header value must exactly match the configured value. JWT users with workflow access can also call without the custom header.

## Response Caching

Configure `cache_ttl_seconds` per workflow. When set and greater than 0:

- **Cache key**: SHA256 hash of `workflow_id` + `body` + `query`
- **Cache hit**: Returns immediately with `status: "cached"` and cached outputs
- **Cache set**: Only after a successful execution (`status: "success"`)
- **Storage**: In-memory; not distributed across multiple instances

| Setting | Effect |
|---------|--------|
| `cache_ttl_seconds` = 0 or null | Caching disabled |
| `cache_ttl_seconds` > 0 | Responses cached for this many seconds |

`test_run` requests bypass the cache (no read, no write).

## Rate Limiting

Configure per workflow: `rate_limit_requests` and `rate_limit_window_seconds`.

- **Scope**: Per `workflow_id` + client IP (sliding window)
- **Exceeded**: HTTP 429 with `Retry-After` header
- **Headers**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

| Setting | Description |
|---------|-------------|
| `rate_limit_requests` | Max requests allowed in the window |
| `rate_limit_window_seconds` | Window duration in seconds |

`test_run` requests bypass rate limiting.

## Response Format

The endpoint returns JSON:

```json
{
  "workflow_id": "uuid",
  "status": "success",
  "outputs": { ... },
  "execution_time_ms": 123
}
```

| Field | Description |
|-------|-------------|
| `workflow_id` | Workflow UUID |
| `status` | `success`, `error`, `cached`, or `rate_limited` |
| `outputs` | Terminal node outputs. With a single [JSON output mapper](../nodes/json-output-mapper-node.md) as the only terminal, the response body is that mapped object at the top level (default simple JSON responses). Otherwise includes [Output](../nodes/output-node.md) and other terminals keyed by label. |
| `execution_time_ms` | Execution time in milliseconds (0 for cached/rate_limited) |

On error, `outputs` may contain error details. A [Throw Error](../nodes/throw-error-node.md) node can set a custom HTTP status code (4xx/5xx).

## Run with cURL Dialog

The **Run with cURL** toolbar button (top-right of the editor, `cURL` icon) opens a dialog that builds and copies a ready-to-run cURL command for the current workflow.

### What It Does

| Field | Description |
|-------|-------------|
| **Request Body Mode** | Choose **Defined** or **Generic**. Generic keeps the body as raw JSON instead of shaping it from Input fields. |
| **Authentication** | Choose Anonymous, JWT Token, or Header Auth. Sets the correct auth header in the command. |
| **Header Key / Value** | Visible when Header Auth is selected. Pre-filled from the workflow's auth settings. |
| **Response Cache** | Minutes to cache identical responses (0 = disabled). Changes are saved to the workflow. |
| **Rate Limit** | Max requests per time window. Changes are saved to the workflow. |
| **SSE Streaming** | Switches the command to `/execute/stream`, adds `--no-buffer`, and exposes per-node `node_start` message settings. |
| **Body** | JSON request body. In Defined mode it is pre-filled from [Input](../nodes/input-node.md) fields and keeps empty keys. In Generic mode it is a raw JSON editor. |
| **Command** | Read-only preview of the full cURL command. |

Click **Copy cURL** to copy the command to the clipboard.

### Example

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-value" \
  "https://app.heym.ai/api/workflows/{workflow_id}/execute" \
  -d '{"message": "Hello"}'
```

In Generic mode, nested payloads stay intact, for example:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  "https://app.heym.ai/api/workflows/{workflow_id}/execute" \
  -d '{"event":{"user":{"id":"123"}}}'
```

The dialog mirrors the authentication, body mode, caching, and rate-limit settings stored on the workflow — editing them here updates the workflow immediately.

### SSE Streaming in the Dialog

Enable **SSE Streaming** when you want the generated command to follow execution in real time from your terminal.

- The endpoint changes from `/execute` to `/execute/stream`
- The command adds `--no-buffer` and `Accept: text/event-stream`
- Each non-sticky node appears in a list where you can:
  - enable or disable the `node_start` message
  - customize the start message text
- `node_complete` events are always emitted and include the full node output

Example:

```bash
curl -X POST --no-buffer \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer <your-access-token>" \
  "https://app.heym.ai/api/workflows/{workflow_id}/execute/stream" \
  -d '{"message":"Hello"}'
```

For the complete event protocol and examples, see [SSE Streaming](./sse-streaming.md).

## Trigger Source Tagging

Every execution stores a `trigger_source` label visible in [Execution History](./execution-history.md). Set it by sending the `X-Trigger-Source` header with any value you choose:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-Trigger-Source: my-service" \
  "https://app.heym.ai/api/workflows/{workflow_id}/execute" \
  -d '{"message": "Hello"}'
```

The **Copy cURL** button in the editor dialog includes `X-Trigger-Source: API` automatically. You can replace `API` with anything meaningful — `scheduler`, `rabbitmq`, `github-actions`, etc.

If the header is not sent, `trigger_source` defaults to `"API"` and the run is labelled **API** in history. Override it with any value meaningful to your system — `scheduler`, `github-actions`, `rabbitmq`, etc.

## Related

- [SSE Streaming](./sse-streaming.md) – Stream node events in real time via Server-Sent Events
- [Triggers](./triggers.md) – All workflow entry points including webhook
- [Workflow Structure](./workflow-structure.md) – Nodes and edges
- [Expression DSL](./expression-dsl.md) – Access `$input.body`, `$input.headers`, `$input.query`
