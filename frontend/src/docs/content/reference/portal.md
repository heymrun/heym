# Portal

The **Portal** exposes Heym workflows as public chat-style UIs. End users can run workflows via a URL without logging into Heym.

## What It Does

- **Public URL**: `/chat/{slug}` (e.g. `/chat/my-workflow`)
- **Chat interface**: Users interact through a chat UI (messages, inputs, responses)
- **Optional auth**: If portal users are configured, login is required; otherwise the portal is public
- **Streaming**: Real-time node progress during execution (when enabled)
- **Stop running executions**: Users can stop an in-flight portal run from the chat footer; the active workflow execution is cancelled server-side as well
- **File upload**: Optional file uploads (text, images, etc.) per input field
- **Human review handoff**: Portal runs can surface [HITL review links](./human-in-the-loop.md) when an agent pauses for approval
- **Image display**: Workflow outputs containing images (e.g. from LLM image generation or Playwright screenshots) appear as thumbnails in the chat. Click any image to open a fullscreen viewer; press **Esc** or use the device back button to close

## Workflow Configuration

| Setting | Description |
|---------|-------------|
| `portal_enabled` | Enable portal for this workflow |
| `portal_slug` | URL slug (e.g. `my-workflow` → `/chat/my-workflow`) |
| `portal_stream_enabled` | Use streaming execution |
| `portal_file_upload_enabled` | Allow file uploads |
| `portal_file_config` | Per-field file config (types, limits) |

Configure in the editor: **Portal** button in the workflow header opens the portal settings dialog.

## Flow

1. **Info**: `GET /api/portal/{slug}/info` – Returns workflow metadata and input fields (no auth)
2. **Login** (if required): `POST /api/portal/{slug}/login` – Returns session token
3. **Execute**: `POST /api/portal/{slug}/execute` – The portal chat UI calls this (or its streaming variant internally when enabled); end users interact via the chat interface, not by calling the API directly.
4. **Stop**: `POST /api/portal/{slug}/executions/{execution_id}/cancel` – Requested when the user presses **Stop** during an active portal run

## HITL in Portal Runs

If a portal workflow reaches an [Agent Node](../nodes/agent-node.md) with [Human-in-the-Loop](./human-in-the-loop.md) enabled, the portal response shows a review link instead of appearing empty.

- The workflow execution status becomes `pending`
- The portal chat displays the review URL
- Any nodes connected to the agent's `review` output handle can notify Slack, email, or other channels immediately
- A reviewer completes the decision on `/review/{token}` without logging in
- After review, the workflow resumes from the stored snapshot

This makes it possible to combine public chat flows with private human approval steps.

## Input Fields

Input fields come from [Input](../nodes/input-node.md) nodes. The API extracts start nodes of type `textInput` and their `inputFields`. Execution uses the same engine as normal runs; inputs are passed as `body.inputs` and `conversation_history` for multi-turn flows.

## Auth and Sessions

- **WorkflowPortalUser**: Username/password per workflow (when auth is enabled)
- **PortalSession**: Session tokens with 168-hour TTL
- **Rate limiting**: 3 failed login attempts → 24h ban per workflow+IP
- Expired sessions are cleaned by a cron job

## Configuration UI

**WebPortalSettingsDialog** tabs:

1. **General**: Enable portal, set slug, copy portal URL
2. **Users**: Add/remove portal users (username/password)
3. **Options**: Stream mode, file upload, view input fields

## Related

- [Why Heym](../getting-started/why-heym.md) – Portal as an AI-native feature
- [Workflows Tab](../tabs/workflows-tab.md) – Create workflows and enable portal
- [Human-in-the-Loop](./human-in-the-loop.md) – Public review pages for pending agent outputs
- [Triggers](./triggers.md) – Portal as an entry point
- [Node Types](./node-types.md) – [Input](../nodes/input-node.md) for portal inputs
- [Workflow Structure](./workflow-structure.md) – Nodes and edges
