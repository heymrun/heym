# MCP Tab

The **MCP** tab configures Model Context Protocol (MCP) integration. MCP lets AI clients (Claude, Cursor, and any MCP-compatible tool) call your Heym workflows as tools.

Heym supports two modes: a **default server** that exposes all MCP-enabled workflows under a single endpoint, and **named servers** that give each logical group of workflows its own dedicated URL and API key.

Both modes can expose two kinds of tools: individual **workflows**, and the **Heym chat tool** — the whole [Chat tab](./chat-tab.md) engine behind one `heym_chat` tool.

<video src="/features/showcase/mcp.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/mcp.webm">▶ Watch MCP demo</a></p>

## Default MCP Server

The default server is always available at `{origin}/api/mcp/sse`. All workflows with MCP toggled on appear as tools here.

### MCP API Key

- The tab shows your MCP API key (masked)
- **Regenerate** – Create a new API key if needed
- Use this key when connecting Claude Desktop, Cursor, or other MCP clients to Heym

### Connection Methods

- **API Key** – Use the MCP API key for programmatic connections. The tab can copy a ready-to-use JSON config and includes an **Add to Cursor** button for one-click Cursor setup.
- **Claude** – The tab shows the MCP server URL and setup steps for Claude. Leave OAuth Client ID and Secret blank; Claude registers automatically and authenticates via Heym OAuth.

### Workflow MCP Toggle

Each workflow can be exposed as an MCP tool:

- **Enable** – The workflow's tools become available to all clients connected to the default server
- **Disable** – The workflow is not exposed

Workflow cards show the description and a preview of input field names so you can see what each tool expects before enabling it.

## Heym Chat Tool

The **Heym Capabilities** section turns the Chat tab engine into a single MCP tool named `heym_chat`. Enable it on the default server, on any named server, or on both — each surface keeps its own toggle and model selection.

When it is on, `heym_chat` appears in `tools/list` alongside your workflow tools. An MCP client sends one natural-language message and the Heym engine takes it from there, with the same abilities the Chat tab has:

- Build, edit, inspect, and run workflows through the Workflow AI Builder
- Report analytics, recent executions, and upcoming cron schedules
- Report what is running right now: how many executions are active, their workflow names, how long each has been running, the node each is currently on, and a link to the live run
- List boards, create cards, and read card detail on the [Board tab](./board-tab.md)
- Read teams and global variables, and search the documentation
- Approve, edit, or refuse pending human-in-the-loop reviews

Capabilities added to the Chat tab later become available through `heym_chat` automatically — there is no per-capability toggle to keep in sync.

### Credential and model

`heym_chat` runs the engine on your Heym account, so it needs an LLM credential of its own:

| Field | Behavior |
|-------|----------|
| **Credential** | Pick any OpenAI, Google, or Custom credential you can access. Prefilled from the preferred credential in [Settings](../reference/user-settings.md) when you have not chosen one. |
| **Model** | Loaded from the selected credential. Prefilled from your preferred model when the credential matches. |

If either is missing, the tool still appears in `tools/list` but each call returns an error telling you to finish the setup in this tab.

### Arguments and history

| Argument | Required | Description |
|----------|----------|-------------|
| `message` | Yes | The instruction or question, in natural language. |
| `conversation_id` | No | A `conversation_id` from a previous `heym_chat` result, to continue that thread. |

Every call is written to your [Chat tab](./chat-tab.md) history as a normal conversation, marked with a plug icon in the conversation list. Messages, tool cards, and clarification pauses look exactly like a conversation you started yourself, and you can open the thread and keep talking in the browser. Each result returns its `conversation_id` so the MCP client can continue the same thread instead of opening a new one on every call.

When the assistant needs clarification, it pauses and says so; reply with the answers using the same `conversation_id`.

## Named MCP Servers

Named servers let you segment workflows into isolated MCP endpoints. Each server has its own URL and API key, so different AI clients, teams, or use cases can connect to exactly the workflows they need.

### Creating a Named Server

1. Type a name in the input field at the bottom of the MCP tab (e.g. **CRM Tools**)
2. Click **Create** — a new server card appears immediately
3. Click the card to expand it

### Per-Server Settings

Each server card shows:

| Setting | Description |
|---------|-------------|
| **SSE Endpoint** | Unique URL: `{origin}/api/mcp/servers/{uuid}/sse` |
| **API Key** | Independent key; reveal with the eye icon, copy or regenerate as needed |
| **How to connect** | **Copy JSON** copies the ready-to-paste MCP config; **Add to Cursor** installs it in one click |
| **Heym Capabilities** | Toggle the `heym_chat` tool for this server and pick its credential and model |
| **Assigned Workflows** | Toggle which of your workflows this server exposes |

### Workflow Assignment

Workflow assignment is per-server and independent of the default server toggle. A workflow can be enabled on the default server and on multiple named servers simultaneously, or on none.

Toggling a workflow moves it to the top of the assigned list, so the row you just changed stays visible instead of scrolling away.

### Authentication

Named servers support the same authentication methods as the default server:

- **X-MCP-Key header** – Pass the server's API key directly (API clients, Cursor)
- **Claude OAuth** – Add the server URL to Claude integrations; leave credentials blank and Claude registers via OAuth automatically
- **Session token** – Issued during the SSE handshake; scoped to the specific server so tokens from one named server cannot access another

### Deleting a Named Server

Click the **X** icon on a server card header. Deletion removes the server and all its workflow assignments; workflows themselves are not affected.

## SSE Endpoint

| Server | Endpoint |
|--------|----------|
| Default | `{origin}/api/mcp/sse` |
| Named | `{origin}/api/mcp/servers/{server-uuid}/sse` |

Both endpoints support the SSE transport (GET, MCP spec 2024-11-05) and Streamable HTTP transport (POST, MCP spec 2025-03-26). Claude uses OAuth 2.1 / PKCE for secure sign-in on both.

## Related

- [Why Heym](../getting-started/why-heym.md) – MCP as a first-class primitive in Heym
- [Agent Node](../nodes/agent-node.md) – Agent node with MCP tool support
- [Agent Architecture](../reference/agent-architecture.md) – MCP client, tool dispatch, orchestrator
- [Triggers](../reference/triggers.md) – MCP as a workflow entry point
- [Chat Tab](./chat-tab.md) – The engine behind the `heym_chat` tool
- [Workflows Tab](./workflows-tab.md) – Create and manage workflows
- [Node Types](../reference/node-types.md) – AI nodes overview
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
