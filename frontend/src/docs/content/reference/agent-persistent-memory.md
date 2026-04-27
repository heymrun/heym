# Agent Persistent Memory

Agent nodes can keep a **per-node knowledge graph** stored in the database: entities (with types and properties) and relationships between them. When enabled, Heym **injects a summary of that graph into the system prompt** on each run (if the graph is non-empty). After a successful run, an **LLM extraction job** merges new facts from the conversation into the graph in the background.

Sub-agents and orchestrators each use the graph tied to **their own canvas node** by default. You can also **grant other agents read or read/write access** to this node’s graph (including agents in **other workflows** you own)—see [Sharing with other agents](#sharing-with-other-agents).

## Enabling

| Parameter | Type | Description |
|-----------|------|-------------|
| `persistentMemoryEnabled` | boolean | When `true`, load this node’s graph into the system prompt and schedule post-run extraction for this node’s graph |
| `memoryShares` | array (optional) | Grants other agent nodes access to **this** node’s memory graph; see [Sharing](#sharing-with-other-agents) |

Turn it on in the Agent node properties (**Persistent memory (graph)**). A pink **brain** icon on the node opens the graph editor when memory is enabled (or when a model is shown).

## Graph editor

The dialog provides a visual graph of entities and edges, plus editing and navigation (fit view, keyboard shortcuts). You can **add, edit, or delete** nodes and edges manually; changes apply to **this** agent’s graph only (the graph for the canvas node whose brain you opened).

## Sharing with other agents

In the memory graph dialog, **Share memory with other agents** lets you attach **peers** that may consume this graph at runtime:

1. Choose a **workflow** (any workflow you can open in the editor).
2. Choose an **agent** node in that workflow.
3. Set **Read only** or **Read & write**.

| Permission | Effect |
|------------|--------|
| Read only | When the **peer** agent runs, this graph is merged into the peer’s system prompt (if it has entities). No extraction into this graph from the peer’s run. |
| Read & write | Same prompt behavior as read, and after a **successful** peer completion, the usual memory extraction may also **merge into this (owner) graph** using the peer run’s credential. |

Peers are stored per owner node as `memoryShares` entries with `peerWorkflowId` and `peerCanvasNodeId` (and `permission`). Older workflows may omit `peerWorkflowId` for peers in the **same** workflow; the editor treats that as the current workflow.

**Cross-workflow sharing** is resolved at run time by scanning workflows **you own**. Runs without an authenticated user context only resolve shares defined in the **current** workflow’s JSON (same canvas).

## Runtime behavior

### Own graph (`persistentMemoryEnabled`)

1. **Before the LLM call** — If the graph has entities, a block is appended to the system instruction explaining that these are facts from prior runs (may be incomplete; current user message wins on conflict).
2. **After a successful completion** — A background job asks the model (same credential as the agent run) for structured JSON (entities + relationships). That payload is merged into the database (deduplication and relationship cleanup apply for some types, e.g. employment-style edges).

### Peer receiving shared graphs

When an agent runs, the system finds **owner** nodes (in any of your workflows, when possible) whose `memoryShares` point at this run’s workflow and canvas node. For each match, that owner’s graph is appended as a **shared memory** section in the system prompt. **Read & write** peers additionally schedule extraction targets for the **owner** workflow/graph when the run succeeds.

Extraction does **not** run when the run errors or ends in a HITL pending state.

## Workflow JSON (`data` field)

Persisted on the agent node like other settings:

```json
{
  "type": "agent",
  "data": {
    "label": "supportAgent",
    "persistentMemoryEnabled": true,
    "userMessage": "$input.text",
    "memoryShares": [
      {
        "peerWorkflowId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "peerCanvasNodeId": "agent-peer-canvas-id",
        "permission": "read"
      }
    ]
  }
}
```

`permission` is `"read"` or `"write"`. Omit `memoryShares` or use `[]` when no sharing.

See [Workflow Structure](./workflow-structure.md) for the full node object shape.

## Related

- [Agent Node](../nodes/agent-node.md) — Full agent configuration
- [Agent Architecture](./agent-architecture.md) — Orchestrator, sub-agents, tools
- [Workflow Structure](./workflow-structure.md) — JSON workflow format
- [Canvas Features](./canvas-features.md) — Brain control and graph dialog
- [Traces tab](../tabs/traces-tab.md) — LLM request/response observability
