# Core Concepts

## Workflows

A workflow is a directed graph of [**nodes**](../reference/node-types.md) connected by **edges**. Manage workflows in the [Workflows](../tabs/workflows-tab.md) tab. Organize them in [folders](../reference/workflow-organization.md). Execution flows from [trigger nodes](../reference/triggers.md) ([Input](../nodes/input-node.md), [Cron](../nodes/cron-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [IMAP Trigger](../nodes/imap-trigger-node.md), [WebSocket Trigger](../nodes/websocket-trigger-node.md)) through processing nodes to [output](../nodes/output-node.md) nodes. See [Workflow Structure](../reference/workflow-structure.md) for the JSON format. Save and share workflows as [Templates](../tabs/templates-tab.md) to reuse them across projects.

## Nodes

Each node has:

- **Type** – Determines behavior (e.g. `llm`, `condition`, `http`)
- **Data** – Configuration (model, prompt, URL, etc.)
- **Inputs/Outputs** – Handles for connecting to other nodes

See [Node Types](../reference/node-types.md) for the full list.

## Edges

Edges connect a source node's output handle to a target node's input handle. Data flows along edges during execution.

## Execution Flow

1. **Trigger** – Input, Cron, Telegram Trigger, IMAP Trigger, or [WebSocket Trigger](../nodes/websocket-trigger-node.md) node starts execution (see [Triggers](../reference/triggers.md))
2. **Downstream** – Each node receives output from connected upstream nodes; [parallel execution](../reference/parallel-execution.md) runs independent nodes concurrently
3. **Expressions** – Nodes reference upstream data via `$nodeLabel.field`. See [Expression DSL](../reference/expression-dsl.md).
4. **Output** – [Output](../nodes/output-node.md) node produces the final result

## Expression References

Use `$input` for the Input node's data and `$nodeLabel.field` for any upstream node. Example: `$llm.text` references the `text` field from a node labeled "llm". Full syntax: [Expression DSL](../reference/expression-dsl.md). Use the [Expression Evaluation Dialog](../reference/expression-evaluation-dialog.md) for a larger editor with live backend preview when editing expressions.

## Related

- [Quick Start](./quick-start.md) – Build your first workflow
- [Canvas Features](../reference/canvas-features.md) – Data pin, execution logs, enable/disable, extract to sub-workflow
- [AI Assistant](../reference/ai-assistant.md) – Create workflows with natural language
- [Node Types](../reference/node-types.md) – All available nodes
- [Expression DSL](../reference/expression-dsl.md) – Referencing data in expressions
- [Expression Evaluation Dialog](../reference/expression-evaluation-dialog.md) – Expandable editor with live backend preview
- [Workflows Tab](../tabs/workflows-tab.md) – Manage workflows and folders
- [Workflow Organization](../reference/workflow-organization.md) – Folders and scheduled deletion
- [Triggers](../reference/triggers.md) – Entry points for workflows
- [Webhooks](../reference/webhooks.md) – HTTP webhook trigger (TTL, cache, rate limit)
- [Parallel Execution](../reference/parallel-execution.md) – How nodes run in parallel
