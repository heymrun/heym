# MCP Call Node

The **MCP Call** node calls a specific [Model Context Protocol (MCP)](https://modelcontextprotocol.io) tool directly, without an LLM deciding which tool to invoke. Use it when you know exactly which tool to call and want deterministic, single-step execution.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.result` |

## When to Use

Use the MCP Call node when:
- You know exactly which MCP tool to call at design time
- You do not need an LLM to choose between tools
- You want a lightweight, deterministic alternative to an agent node for a single tool invocation

Use the [Agent node](./agent-node.md) instead when an LLM should decide which tools to call or when you need multi-step reasoning.

> The MCP Call node **cannot** be connected to an agent node as a tool.

## Connection Configuration

The node connects to a single MCP server. Choose a transport and fill in the corresponding fields.

### SSE / Streamable HTTP

| Field | Description |
|-------|-------------|
| `transport` | `sse` or `streamable_http` |
| `url` | Full URL of the MCP server (e.g. `https://mcp.example.com/sse`). Supports DSL expressions. |
| `headers` | JSON object of HTTP headers (e.g. `{"Authorization": "Bearer ..."}`) |
| `timeoutSeconds` | Per-connection timeout in seconds (default: 30) |

### stdio

| Field | Description |
|-------|-------------|
| `transport` | `stdio` |
| `command` | Executable to run (e.g. `npx`) |
| `args` | JSON array of arguments (e.g. `["-y", "@modelcontextprotocol/server-filesystem"]`) |
| `env` | JSON object of environment variables (e.g. `{"API_KEY": "..."}`) |
| `timeoutSeconds` | Per-connection timeout in seconds (default: 30) |

## Tool Selection

1. Fill in the connection fields.
2. Click **Fetch Tools** — the node connects to the MCP server and lists available tools.
3. Select a tool from the dropdown.

**Tool selection is required.** The node will not execute without a selected tool.

## Arguments

After selecting a tool, the node renders one input field per argument defined in the tool's input schema. Each field accepts:
- A static value: `10`
- A DSL expression: `$userInput.body.text`

Required arguments are marked with `*`.

## Output

| Field | Description |
|-------|-------------|
| `$nodeLabel.result` | Tool result. If the response is valid JSON, this is a parsed object. Otherwise it is a string. |

## Example

Call a `search` tool on an SSE MCP server, passing the user's query:

```json
{
  "type": "mcpCall",
  "data": {
    "label": "searchCall",
    "connection": {
      "transport": "sse",
      "url": "https://mcp.example.com/sse",
      "timeoutSeconds": 30
    },
    "selectedTool": "search",
    "toolArguments": {
      "query": "$userInput.body.text",
      "limit": "10"
    },
    "timeoutSeconds": 30
  }
}
```

Access the result downstream:

```
$searchCall.result.items   ← if result is a JSON object
$searchCall.result         ← if result is a plain string
```

## Notes

- The node resolves DSL expressions in `url`, `headers`, `env`, and all `toolArguments` values before calling the tool.
- The `timeoutSeconds` at the node level applies to the overall execution; the `connection.timeoutSeconds` applies to the MCP session itself.
- If the MCP server is unavailable or returns an error, the node fails and the error message is available in the workflow trace.
