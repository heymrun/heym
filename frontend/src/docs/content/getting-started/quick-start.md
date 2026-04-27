# Quick Start

Get your first Heym workflow running in minutes.

## 1. Create a Workflow

1. Go to the [Workflows](../tabs/workflows-tab.md) tab
2. Click **New Workflow**
3. Name your workflow (e.g. "Hello World")

## 2. Add Nodes

1. Open the **Nodes** panel on the left
2. Drag an [Input](../nodes/input-node.md) node onto the canvas
3. Drag an [LLM](../nodes/llm-node.md) node and connect it to the Input
4. Drag an [Output](../nodes/output-node.md) node and connect it to the LLM

```
[Input] --> [LLM] --> [Output]
```

See [Node Types](../reference/node-types.md) for all available nodes.

## 3. Configure

- **Input**: Set a default value or leave empty for user input (see [Input Node](../nodes/input-node.md))
- **LLM**: Select a [credential](../tabs/credentials-tab.md) and model, add a system instruction, and set `userMessage` to `$input.text` (see [LLM Node](../nodes/llm-node.md))
- **Output**: Set `message` to `$llm.text` to pass through the LLM response (see [Output Node](../nodes/output-node.md))

Use [Expression DSL](../reference/expression-dsl.md) syntax for `$input.text` and `$llm.text`. Click the expand button on expression fields for the [Expression Evaluation Dialog](../reference/expression-evaluation-dialog.md) with live backend preview.

## 4. Run

Click **Run**, press `Ctrl + Enter`, or use the debug panel to execute. The workflow runs from the Input node through connected nodes to the Output. See [Triggers](../reference/triggers.md) for other ways to run workflows ([webhook](../reference/webhooks.md), portal, cron, etc.).

View past runs in **History** (toolbar) and use **Bring to Canvas** to re-run with the same inputs.

On Docs, Evals, and other non-canvas internal pages, you can also use the [Quick Drawer](../reference/quick-drawer.md) to pick a pinned workflow and run it without going back to the editor.

If you are reading the docs and want clarification before building, open [Chat with Docs](../reference/chat-with-docs.md) from the Docs header to ask page-aware questions.

Alternatively, use the [AI Assistant](../reference/ai-assistant.md) from the Debug panel to create workflows with natural language—describe what you want and the AI generates nodes and edges.

## Related

- [Core Concepts](./core-concepts.md) – Workflows, nodes, and execution flow
- [Running & Deployment](./running-and-deployment.md) – Start locally with `run.sh` or deploy with `deploy.sh`
- [User Settings](../reference/user-settings.md) – Configure name, User Rules, and password
- [Canvas Features](../reference/canvas-features.md) – Data pin, execution logs, enable/disable, extract to sub-workflow
- [Keyboard Shortcuts](../reference/keyboard-shortcuts.md) – Canvas and editor shortcuts
- [Expression DSL](../reference/expression-dsl.md) – Referencing data in node config
- [Expression Evaluation Dialog](../reference/expression-evaluation-dialog.md) – Expandable editor with live backend preview
- [Triggers](../reference/triggers.md) – All workflow entry points ([webhook](../reference/webhooks.md), portal, cron, etc.)
- [Execution History](../reference/execution-history.md) – View past runs and Bring to Canvas
- [Quick Drawer](../reference/quick-drawer.md) – Run pinned workflows from non-canvas pages
- [Chat with Docs](../reference/chat-with-docs.md) – Ask contextual questions from the docs header
- [Workflows Tab](../tabs/workflows-tab.md) – Create and manage workflows
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for LLM nodes
- [AI Assistant](../reference/ai-assistant.md) – Create workflows with natural language
