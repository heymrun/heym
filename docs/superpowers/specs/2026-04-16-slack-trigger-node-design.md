# Slack Trigger Node — Design Spec

**Date:** 2026-04-16  
**Status:** Approved  
**Scope:** New `slackTrigger` entrypoint node for receiving Slack Events API webhooks

---

## 1. Overview

Add a `slackTrigger` node type that acts as a canvas entrypoint. When placed on the canvas, it generates a **static webhook URL** derived from its node ID. The user pastes this URL into their Slack App's Event Subscriptions page. Slack's URL verification challenge is handled automatically. When Slack sends an event, the workflow is executed with the event payload available downstream via expressions.

---

## 2. Architecture

```
Slack App ──POST──▶ POST /api/slack/webhook/{node_id}
                        │
                        ├─ type == "url_verification"?
                        │      └─▶ {"challenge": "..."} 200 (no workflow execution)
                        │
                        ├─ Verify X-Slack-Signature (HMAC-SHA256)
                        │      signing_secret from slackTrigger credential
                        │      timestamp tolerance: 5 minutes (replay attack prevention)
                        │      no credential → log warning, proceed (loose mode)
                        │
                        ├─ DB: SELECT workflow WHERE nodes @> '[{"id": "<node_id>"}]'
                        │      not found → 404
                        │
                        ├─ Return 200 immediately (Slack 3s timeout)
                        │
                        └─ Background task: execute_workflow(trigger_source="Slack")
                               initial inputs: { event: <body>, headers: {...} }
```

---

## 3. Backend

### 3.1 New file: `backend/app/api/slack.py`

Router prefix: `/api/slack`

**Endpoint:** `POST /webhook/{node_id}`

Responsibilities:
- Parse raw request body (needed for HMAC verification before JSON parsing)
- Handle `url_verification` type: return `{"challenge": value}` immediately
- Verify `X-Slack-Signature` header using HMAC-SHA256 with signing secret from credential
  - Header format: `v0=<hex_digest>`
  - Signing base string: `v0:{timestamp}:{raw_body}`
  - Reject if `|now - timestamp| > 300s`
- JSONB lookup: find workflow whose `nodes` array contains `{"id": node_id}`
- Return `200 OK` immediately
- Fire `asyncio.create_task(execute_workflow(...))` as background task
- `trigger_source = "Slack"`
- Initial inputs injected into node data under `_initial_inputs`:
  ```python
  {"event": <parsed_body>, "headers": <safe_headers>}
  ```

**Error responses:**
- `403`: Invalid signature
- `404`: No workflow found for node_id
- `200`: All other cases (Slack requires 200 even on ignored events)

### 3.2 Credential type: `backend/app/db/models.py`

```python
class CredentialType(str, Enum):
    ...
    slack_trigger = "slack_trigger"
```

Credential config schema (stored encrypted):
```json
{ "signing_secret": "<secret_from_slack_app>" }
```

### 3.3 Workflow executor: `backend/app/services/workflow_executor.py`

Add `slackTrigger` to the entrypoint node handler (same pattern as `cron`):

```python
elif node_type == "slackTrigger":
    trigger_inputs = node_data.get("_initial_inputs", {})
    return {
        "event": trigger_inputs.get("event", {}),
        "headers": trigger_inputs.get("headers", {}),
    }
```

Add `slackTrigger` to the set of 0-input entrypoint node types (alongside `cron`, `textInput`, `errorHandler`).

### 3.4 Router registration: `backend/app/main.py`

```python
from app.api import slack as slack_api
app.include_router(slack_api.router, prefix="/api/slack", tags=["slack"])
```

### 3.5 Tests: `backend/tests/test_slack_trigger.py`

Five test cases using `unittest.IsolatedAsyncioTestCase` + `AsyncMock`:

1. **`test_url_verification`** — POST with `{"type": "url_verification", "challenge": "abc"}` → `{"challenge": "abc"}`, no execution
2. **`test_valid_event_executes_workflow`** — valid signature, known node_id → 200, `execute_workflow` called once
3. **`test_invalid_signature_returns_403`** — wrong HMAC → 403, no execution
4. **`test_replay_attack_returns_403`** — timestamp older than 5 min → 403
5. **`test_unknown_node_id_returns_404`** — no workflow found for node_id → 404

---

## 4. Frontend

### 4.1 Type: `frontend/src/types/workflow.ts`

```typescript
export type NodeType =
  | ...existing...
  | "slackTrigger";
```

### 4.2 Node definition: `frontend/src/types/node.ts`

```typescript
slackTrigger: {
  type: "slackTrigger",
  label: "Slack Trigger",
  description: "Receive Slack events and trigger the workflow",
  color: "node-slack",
  icon: "MessageSquare",
  inputs: 0,
  outputs: 1,
  defaultData: {
    label: "slackTrigger",
    credentialId: "",
  },
}
```

### 4.3 Properties panel: `frontend/src/components/Panels/PropertiesPanel.vue`

New template block for `slackTrigger`:
- **Credential picker**: dropdown filtered to `slack_trigger` credential type
- **Webhook URL**: read-only input showing `{baseUrl}/api/slack/webhook/{node.id}` with a Copy button
- Help text: "Paste this URL into Slack App → Event Subscriptions → Request URL"

`webhookUrl` computed property — uses the API base URL (not `window.location.origin`, since frontend and backend may be on different origins). Read from the existing `axiosInstance.defaults.baseURL` or an env var `VITE_API_BASE_URL`:
```typescript
const webhookUrl = computed(() => {
  if (selectedNode.value?.type !== "slackTrigger") return "";
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? window.location.origin;
  return `${base}/api/slack/webhook/${selectedNode.value.id}`;
});
```

### 4.4 Node panel: `frontend/src/components/Panels/NodePanel.vue`

- Add `slackTrigger` to icon map (use `MessageSquare` icon, same as `slack`)
- Add `slackTrigger` to color map (`node-slack`)
- Add `slackTrigger` to `noInputTypes` array

---

## 5. Workflow DSL Prompt

File: `backend/app/services/workflow_dsl_prompt.py`

Add `slackTrigger` section alongside `cron` and `textInput`:

```
### slackTrigger (Slack Event Entry Point)
- inputs: 0, outputs: 1
- Triggered when Slack sends an event to the workflow's webhook URL
- Output fields:
  - $input.event       — full Slack event object
  - $input.event.type  — event type (e.g. "message", "reaction_added")
  - $input.headers     — incoming HTTP headers (sanitized)
- WHEN TO USE: React to Slack messages, reactions, mentions, app_home_opened, etc.
- Required: credentialId pointing to a slackTrigger credential (signing_secret)
- DO NOT use textInput as entry point when building Slack-triggered workflows
```

---

## 6. Documentation (heym-documentation skill)

- New doc page: "Slack Trigger" under Triggers section
- Content:
  - Create Slack App, enable Event Subscriptions
  - Create `slackTrigger` credential in Heym with signing secret
  - Add node to canvas, copy webhook URL, paste into Slack
  - Challenge verification is automatic
  - Example expressions: `$input.event.type`, `$input.event.text`

---

## 7. heymweb Landing Page

File: `heymweb/src/components/sections/DocumentationSection.tsx` (or integration list component)

- Add Slack to the integrations/features list
- Copy: "Slack Trigger — receive Slack events and automate workflows instantly"

---

## 8. Constraints & Decisions

| Decision | Rationale |
|---|---|
| URL uses `node_id` only | Node ID is a stable UUID set by frontend at creation time; no extra migration needed |
| JSONB containment query | `nodes` column is already JSONB; no schema change needed |
| Immediate 200 + background task | Slack requires response within 3 seconds; workflow execution can take longer |
| `slack_trigger` as new credential type | Keeps send (webhook_url) and receive (signing_secret) credentials separate |
| Loose mode when no credential | Allows quick testing without credential; warning logged. Production deployments should always set a credential. |
| Timestamp replay window: 5 min | Matches Slack's own recommendation |
