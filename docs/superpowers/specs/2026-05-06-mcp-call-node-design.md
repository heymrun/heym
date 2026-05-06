# MCP Call Node — Design Spec

**Date:** 2026-05-06
**Status:** Approved, pending implementation

## Overview

A new `mcpCall` node type that calls a specific MCP (Model Context Protocol) tool directly, without an LLM in the loop. It is standalone — not connected to or dependent on an agent node. Tool selection is mandatory; the node will not execute without it.

## Requirements

- Same MCP connection config as agent node: SSE, streamable HTTP, stdio; fields: url, command, args, env, headers, timeoutSeconds
- Single connection (not an array like agent node)
- Tool selection via "Fetch Tools" button → dropdown (uses existing `/api/mcp/fetch-tools` endpoint)
- Tool arguments populated from the selected tool's inputSchema, each field accepting a static value or DSL expression (`$input.body.text`)
- Smart output: if tool result text is valid JSON, return parsed object; otherwise return string
- Cannot be connected to an agent node as a tool (added to `BLOCKED_AS_TOOL`)
- Frontend validation prevents save/run when `selectedTool` is empty
- Backend unit tests required

## Data Model

### TypeScript (frontend)

```typescript
interface MCPCallNodeData {
  label: string
  connection: AgentMCPConnection        // reuses existing interface
  selectedTool: string                  // required — empty blocks save/run
  toolArguments: Record<string, string> // key → static value or DSL expression
  timeoutSeconds: number                // default: 30
}
```

`AgentMCPConnection` (unchanged, from `frontend/src/types/workflow.ts`):
```typescript
export interface AgentMCPConnection {
  id: string
  transport: "stdio" | "sse" | "streamable_http"
  label?: string
  timeoutSeconds: number
  command?: string
  args?: string[] | string
  env?: Record<string, string>
  url?: string
  headers?: Record<string, string> | string
}
```

### NODE_DEFINITIONS default (frontend/src/types/node.ts)

```typescript
mcpCall: {
  label: "mcpCall",
  connection: { id: "", transport: "sse", timeoutSeconds: 30 },
  selectedTool: "",
  toolArguments: {},
  timeoutSeconds: 30,
}
```

## Execution Flow

```
PropertiesPanel
  1. User configures connection (transport + fields)
  2. "Fetch Tools" → POST /api/mcp/fetch-tools → tool dropdown populated
  3. User selects a tool → selectedTool set
  4. Tool inputSchema rendered → argument fields appear
  5. User fills each field (static value or DSL expression)
  6. If selectedTool is empty → save/run button disabled (red border + tooltip)

WorkflowExecutor (_execute_node_logic, elif node_type == "mcpCall")
  1. Read connection, selectedTool, toolArguments, timeoutSeconds from node_data
  2. Guard: if not selectedTool → raise ValueError
  3. _resolve_mcp_connection(connection, inputs, node_id) — DSL in url/env/headers
  4. resolve_expression(v, inputs) for each toolArguments value
  5. execute_mcp_tool(connection, selected_tool, resolved_args, timeout) — existing function
  6. _extract_tool_result(raw) — smart JSON unwrap
  7. Return {"result": result, "raw": raw}
```

## Frontend Changes

### WorkflowCanvas.vue — BLOCKED_AS_TOOL (line ~75)

```typescript
const BLOCKED_AS_TOOL = new Set<string>([
  "merge", "switch", "loop", "agent", "llm", "condition",
  "execute", "sticky", "errorHandler",
  "cron", "textInput", "telegramTrigger", "websocketTrigger", "slackTrigger", "imapTrigger",
  "mcpCall",  // cannot be used as an agent tool
]);
```

### PropertiesPanel.vue — new mcpCall section

- Connection block: transport dropdown + conditional fields (identical to agent node's single MCP connection UI)
- "Fetch Tools" button: calls `/api/mcp/fetch-tools`, shows loading state and errors
- Tool dropdown: populates from fetch result; empty state shows red border + "Select a tool to use this node"
- Arguments section: iterates `inputSchema.properties` of selected tool, renders key (read-only) + value input (DSL-capable); required fields marked with `*`
- Validation: `selectedTool === ""` → save/run button disabled

### Canvas Node Appearance (BaseNode.vue pattern)

- Icon: `Plug` (Lucide)
- Badge: selected tool name or "No tool selected" (amber color when empty)

## Backend Changes

### workflow_executor.py — new elif branch

```python
elif node_type == "mcpCall":
    connection = node_data.get("connection") or {}
    selected_tool = node_data.get("selectedTool") or ""
    tool_arguments = node_data.get("toolArguments") or {}
    timeout = float(node_data.get("timeoutSeconds") or 30)

    if not selected_tool:
        raise ValueError("mcpCall node requires a tool to be selected")

    connection = self._resolve_mcp_connection(connection, inputs, node_id)

    resolved_args = {
        k: self.resolve_expression(v, inputs)
        for k, v in tool_arguments.items()
    }

    raw = execute_mcp_tool(connection, selected_tool, resolved_args, timeout)
    result = _extract_tool_result(raw)
    node_result = {"result": result, "raw": raw}
```

**Reuses without modification:**
- `_resolve_mcp_connection` — DSL resolve in connection fields
- `execute_mcp_tool` — from `mcp_tool_executor.py`
- `_extract_tool_result` — smart JSON unwrap
- `resolve_expression` — per-argument DSL resolution

### workflow_dsl_prompt.py — new node type section

```
### mcpCall (MCP Tool Call)
- **Purpose**: Directly call a specific tool from an MCP server without an LLM
- **Inputs**: 1 | **Outputs**: 1
- **Tool selection is REQUIRED** — node will not execute without selectedTool
- **Data fields**:
  - `label`: Node identifier (camelCase)
  - `connection`: MCP connection config (transport, url/command, args, env, headers, timeoutSeconds)
  - `selectedTool`: Tool name to call (must be non-empty)
  - `toolArguments`: key→value pairs; values support DSL expressions
  - `timeoutSeconds`: Execution timeout in seconds (default: 30)
- **Output**:
  - `$label.result` — unwrapped value (JSON object if parseable, otherwise string)
  - `$label.raw` — full MCP content array
- **WHEN TO USE**: When you know exactly which MCP tool to call and do not need an LLM to decide.
- **DO NOT** connect mcpCall to agent tool-input handles.

Example:
{"type": "mcpCall", "data": {"label": "searchCall", "connection": {"transport": "sse", "url": "https://mcp.example.com/sse", "timeoutSeconds": 30}, "selectedTool": "search", "toolArguments": {"query": "$userInput.body.text"}, "timeoutSeconds": 30}}
```

## Backend Unit Tests

File: `backend/tests/test_mcp_call_node.py`

| Test | What it verifies |
|------|-----------------|
| `test_basic_tool_call` | connection + selectedTool + toolArguments → correct execute_mcp_tool call, correct output keys |
| `test_json_result_unwrapped` | MCP returns JSON string → result is parsed object |
| `test_string_result_passthrough` | MCP returns plain text → result is string |
| `test_missing_tool_raises` | selectedTool="" → ValueError raised |
| `test_dsl_arguments_resolved` | `"$input.text"` argument → resolved before tool call |
| `test_connection_dsl_resolved` | `"$input.serverUrl"` in url → resolved before tool call |
| `test_timeout_passed` | timeoutSeconds=60 in node_data → execute_mcp_tool called with 60.0 |

## Landing Page Changes

### NodesSection.tsx — nodes array addition

```typescript
{
  id: 'mcpCall',
  name: 'MCP Call',
  categories: ['ai', 'integration'],
  icon: Plug,
  description: 'Call a specific MCP tool directly — no LLM required. Configure SSE, streamable HTTP, or stdio transport with typed arguments resolved from workflow expressions.',
}
```

## Documentation (heym-documentation skill)

A new node doc file must be created via the `heym-documentation` skill during implementation:
- `frontend/src/docs/content/nodes/mcp-call-node.md` — covers connection config, tool selection, argument DSL, output fields, and a usage example

## What Is NOT Changed

- `mcp_tool_executor.py` — no changes, `execute_mcp_tool` used as-is
- `AgentMCPConnection` interface — reused, not modified
- `/api/mcp/fetch-tools` endpoint — reused as-is
- Agent node behavior — unchanged
- `_build_node_tool_schemas` — `mcpCall` nodes won't appear here since `BLOCKED_AS_TOOL` prevents the edge from being created; no backend change needed
