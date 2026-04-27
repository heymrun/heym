# MCP Tab

The **MCP** tab configures Model Context Protocol (MCP) integration. MCP lets external tools and data sources expose capabilities to [Agent](../nodes/agent-node.md) nodes.

<video src="/features/showcase/mcp.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/mcp.webm">▶ Watch MCP demo</a></p>

## MCP API Key

- The tab shows your MCP API key (masked)
- **Regenerate** – Create a new API key if needed
- Use this key when connecting Claude Desktop, Cursor, or other MCP clients to Heym

## Connection Methods

- **API Key** – Use the MCP API key for programmatic connections. The tab can copy a ready-to-use JSON config and includes an **Add to Cursor** button for Cursor.
- **Claude** – The tab shows the MCP server URL and setup steps for Claude. Leave OAuth Client ID and Secret blank; Claude registers automatically and authenticates via Heym OAuth.

## Workflow MCP Toggle

Each workflow with an [Agent](../nodes/agent-node.md) node can expose its tools via MCP:

- **Enable** – The workflow's tools become available to MCP clients
- **Disable** – The workflow is not exposed

Toggle MCP per workflow from the workflow list on this tab.

Workflow cards also show the workflow description and a preview of input field names so you can see what each exposed tool expects before enabling it.

## SSE Endpoint

MCP clients connect to the Heym backend via Server-Sent Events (SSE). The endpoint is:

```
{origin}/api/mcp/sse
```

Claude uses OAuth 2.1 / PKCE for secure sign-in. API key clients can connect directly with the generated config snippet.

## Related

- [Why Heym](../getting-started/why-heym.md) – MCP as a first-class primitive in Heym
- [Agent Node](../nodes/agent-node.md) – Agent node with MCP tool support
- [Agent Architecture](../reference/agent-architecture.md) – MCP client, tool dispatch, orchestrator
- [Triggers](../reference/triggers.md) – MCP as a workflow entry point
- [Workflows Tab](./workflows-tab.md) – Create and manage workflows
- [Node Types](../reference/node-types.md) – AI nodes overview
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
