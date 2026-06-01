# MCP Tab

The **MCP** tab configures Model Context Protocol (MCP) integration. MCP lets AI clients (Claude, Cursor, and any MCP-compatible tool) call your Heym workflows as tools.

Heym supports two modes: a **default server** that exposes all MCP-enabled workflows under a single endpoint, and **named servers** that give each logical group of workflows its own dedicated URL and API key.

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
| **Assigned Workflows** | Toggle which of your workflows this server exposes |

### Workflow Assignment

Workflow assignment is per-server and independent of the default server toggle. A workflow can be enabled on the default server and on multiple named servers simultaneously, or on none.

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
- [Jungle Grid](../reference/jungle-grid.md) – Run GPU workloads from Agent nodes through an MCP preset
- [Agent Architecture](../reference/agent-architecture.md) – MCP client, tool dispatch, orchestrator
- [Triggers](../reference/triggers.md) – MCP as a workflow entry point
- [Workflows Tab](./workflows-tab.md) – Create and manage workflows
- [Node Types](../reference/node-types.md) – AI nodes overview
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
