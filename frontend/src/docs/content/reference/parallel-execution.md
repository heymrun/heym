# Parallel Execution

Heym runs nodes in parallel when they have no dependencies on each other, and allows multiple workflow runs to execute concurrently.

## Within a Single Run

### DAG-Based Scheduling

The executor groups nodes by **execution level** using a directed acyclic graph (DAG):

1. **Level 0** – Nodes with no incoming edges (start nodes)
2. **Level N** – Nodes whose upstream dependencies are all in levels 0..N-1

Nodes in the same level have no dependencies on each other and run in parallel.

### Thread Pool

- **Shared pool**: `ThreadPoolExecutor(max_workers=8)` for node execution
- **Scheduling**: `wait(..., return_when=FIRST_COMPLETED)` – as soon as any node finishes, downstream nodes are scheduled
- **Thread-safe**: Node outputs are stored with a lock (`store_node_output`)

### Orchestrator Sub-Agents

When an orchestrator agent returns multiple `call_sub_agent` tool calls in one turn, they run in parallel. See [Agent Architecture](./agent-architecture.md).

### Merge Node

The [Merge](../nodes/merge-node.md) node combines outputs from multiple parallel branches. Use it when you explicitly need to combine results; otherwise parallel branches can end in separate output nodes.

### Loops

Loop iterations run **sequentially**. The loop body nodes are re-scheduled per iteration.

### Early Return

Output nodes with `allowDownstream` can return early. Remaining downstream work runs in the background.

## Concurrent Workflow Runs

- **No per-workflow lock** – Multiple requests can run the same workflow at the same time
- **Async API** – FastAPI endpoints use `asyncio.to_thread(execute_workflow)` so the event loop stays responsive
- **Isolation** – Each run gets its own `WorkflowExecutor` instance and state

Triggers that run workflows ([Webhook](./webhooks.md), [Portal](./portal.md), [Cron](./triggers.md), RabbitMQ, MCP, Editor) each call `execute_workflow` independently.

## Streaming

Streaming uses the same parallel model but emits events as nodes complete. The editor and portal chat UI use streaming internally for real-time progress, and webhook users can now opt into the same event stream through the [SSE Streaming](./sse-streaming.md) execute endpoint.

## Related

- [Why Heym](../getting-started/why-heym.md) – DAG-based parallel execution vs sequential tools
- [Workflow Structure](./workflow-structure.md) – Nodes, edges, and execution flow
- [Core Concepts](../getting-started/core-concepts.md) – Execution flow overview
- [Node Types](./node-types.md) – [Merge](../nodes/merge-node.md) node and other types
- [Triggers](./triggers.md) – Entry points that trigger runs
- [SSE Streaming](./sse-streaming.md) – Event stream format for `/execute/stream`
