# Workflow Structure

Workflows are stored as JSON with nodes and edges. See [Node Types](./node-types.md) for available node types and [Expression DSL](./expression-dsl.md) for expression syntax in `data` fields.

## Workflow Object

```json
{
  "id": "uuid",
  "name": "My Workflow",
  "description": "Optional description",
  "nodes": [],
  "edges": [],
  "auth_type": "anonymous",
  "allow_anonymous": true
}
```

## Node Object

```json
{
  "id": "node-uuid",
  "type": "llm",
  "position": { "x": 100, "y": 200 },
  "data": {
    "label": "llm",
    "model": "gpt-4",
    "userMessage": "$input.text"
  }
}
```

### Agent node `data` (persistent memory)

[Agent](../nodes/agent-node.md) nodes support an optional knowledge graph per canvas node:

| Field | Type | Description |
|-------|------|-------------|
| `persistentMemoryEnabled` | boolean | When `true`, load stored graph into the system prompt and merge new facts after successful runs |
| `memoryShares` | array (optional) | Grants other agents access to this node’s memory graph (`peerWorkflowId`, `peerCanvasNodeId`, `permission`: `read` \| `write`). See [Agent Persistent Memory](./agent-persistent-memory.md). |

Example:

```json
{
  "id": "agent-main",
  "type": "agent",
  "position": { "x": 200, "y": 120 },
  "data": {
    "label": "assistant",
    "persistentMemoryEnabled": true,
    "credentialId": "uuid",
    "model": "gpt-4o",
    "userMessage": "$input.text",
    "memoryShares": []
  }
}
```

See [Agent Persistent Memory](./agent-persistent-memory.md) for API paths, editor behavior, and extraction semantics.

## Edge Object

```json
{
  "id": "edge-uuid",
  "source": "input-node-id",
  "target": "llm-node-id",
  "sourceHandle": null,
  "targetHandle": null
}
```

## Node Types

Common `type` values: [Input](../nodes/input-node.md) (`textInput`), [Cron](../nodes/cron-node.md), [WebSocket Trigger](../nodes/websocket-trigger-node.md) (`websocketTrigger`), [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [Condition](../nodes/condition-node.md), [Switch](../nodes/switch-node.md), [Output](../nodes/output-node.md), [JSON output mapper](../nodes/json-output-mapper-node.md) (`jsonOutputMapper`), [Wait](../nodes/wait-node.md), [HTTP](../nodes/http-node.md), [WebSocket Send](../nodes/websocket-send-node.md) (`websocketSend`), [Merge](../nodes/merge-node.md), [Set](../nodes/set-node.md), [Variable](../nodes/variable-node.md), [Loop](../nodes/loop-node.md), and more. Full list: [Node Types](./node-types.md). Nodes in the same execution level run in [parallel](./parallel-execution.md).

## Position

Each node has `position.x` and `position.y` for canvas layout. The editor uses Vue Flow for rendering.

## Related

- [Node Types](./node-types.md) – All node types and descriptions
- [Canvas Features](./canvas-features.md) – Editor features (data pin, execution logs, enable/disable, extract to sub-workflow)
- [Download & Import](./download-import.md) – Export and import workflows as JSON
- [Agent Node](../nodes/agent-node.md) – Agent node `data` structure
- [Agent Persistent Memory](./agent-persistent-memory.md) – `persistentMemoryEnabled`, `memoryShares`, and memory graph API
- [Expression DSL](./expression-dsl.md) – Syntax for `userMessage`, `condition`, `$vars`, `$global`, etc.
- [Parallel Execution](./parallel-execution.md) – How nodes run in parallel
- [Triggers](./triggers.md) – Start nodes and entry points
- [Workflows Tab](../tabs/workflows-tab.md) – Create and manage workflows
