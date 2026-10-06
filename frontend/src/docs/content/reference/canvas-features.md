# Canvas Features

The workflow editor provides several features for debugging, testing, and organizing nodes: **Run to Node**, **Data Pin**, **Execution Logs**, **Enable/Disable**, and **Extract to Sub-Workflow**.

<video src="/features/showcase/editor.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/editor.webm">▶ Watch Editor demo</a></p>

## Run to Node

Hover any node except a sticky note and click **Run** below it. Heym executes that node and its upstream dependencies, leaving downstream nodes and unrelated branches untouched. This uses canvas test mode, including pinned outputs and the workflow's normal branch conditions.

If the selected path has input fields, the right-hand **Run** panel opens and focuses the first field. Enter the values, then click **Run to _node label_** or press **Ctrl+Enter** (Cmd+Enter on macOS). Generic body mode focuses the JSON body editor. Paths without input fields run immediately without opening the panel. Pinned Input nodes reuse their pinned output without asking for input.

The panel keeps the selected target for subsequent runs. Choose **Run full workflow** to clear the target. Run buttons are disabled while an execution is active. A target inside a loop stops the run when that node is first reached; selecting a node after the loop runs the complete upstream loop.

## Data Pin

Data Pin lets you pin a node's output from the last run so you can test downstream nodes without re-executing the pinned node.

### Where to Find It

- **Properties panel** – Select a node and scroll to the **Pinned Data** section
- **Node badge** – A pin icon appears on the node when data is pinned

### Actions

| Action | Description |
|--------|-------------|
| **Pin** | Pins the node's last execution output (available after a run) |
| **Clear** | Removes pinned data |
| **Edit** | Edit the pinned JSON directly; click Save to apply |

### Test Mode Behavior

When running a workflow in test mode, nodes with `pinnedData` skip execution and use the pinned output instead. Use this to:

- Test downstream logic without calling external APIs
- Debug expressions that reference the node's output
- Iterate on prompts or conditions with fixed sample data

Expression completion in the editor uses pinned data when available to suggest fields.

## Execution Logs

The **Debug panel** (bottom drawer) shows real-time execution logs during workflow runs. You
can also open a running production execution from either History dialog or a Board card. The
editor attaches to that run's SSE stream, restores completed node results, and continues to
show node animations and logs as new nodes start and finish.

### What It Shows

- **Node results** – Per-node status (`success`, `error`, `skipped`, `running`), execution time, and output
- **Final outputs** – Aggregated outputs from [Output](../nodes/output-node.md) nodes
- **Agent progress** – For [Agent](../nodes/agent-node.md) nodes, step-by-step tool calls and reasoning

### Actions

- **Copy as JSON** – Copy the full execution log to clipboard
- **Open in JSON editor** – Opens the log in JSON Hero or JSON Editor Online for inspection
- **Download generated files** – If a skill produced downloadable files (`_generated_files`), a Download button appears. Single file downloads directly; multiple files open a selection popup.

### Distinction from Logs Tab

The Debug panel shows **workflow execution** logs (node results, outputs). The [Logs Tab](../tabs/logs-tab.md) shows **Docker container** logs (backend, frontend, database). <!-- pragma: allowlist secret -->

## Enable / Disable

You can disable nodes so they are skipped during execution. Disabled nodes show an "off" badge and appear dimmed.

### How to Toggle

| Method | Description |
|--------|-------------|
| **Properties panel** | Select node → Power icon (top right) |
| **Context menu** | Right-click node(s) → Disable or Enable |
| **Keyboard** | Select node(s) → press **D** (see [Keyboard Shortcuts](./keyboard-shortcuts.md)) |

### Multi-Select

When multiple nodes are selected, Enable/Disable applies to all of them. The context menu shows "Enable" if any selected node is disabled, "Disable" if all are enabled.

### Runtime Behavior

Nodes with `active: false` are skipped. Downstream nodes receive no data from skipped nodes. Use this to temporarily exclude nodes without deleting them.

To switch a node on or off from inside a workflow instead of by hand, use [Disable Node](../nodes/disable-node.md) and [Enable Node](../nodes/enable-node.md).

## Agent memory graph

[Agent](../nodes/agent-node.md) nodes with **[persistent memory](./agent-persistent-memory.md)** enabled show a pink **brain** control on the node. Click it to open the memory graph editor: entities render as an animated, force-directed graph clustered by entity type, with searchable Source/Target pickers for adding relationships and a connections panel for jumping between linked entities. The same dialog includes **Share memory with other agents** (workflow → agent → read or read/write) for [cross-agent memory sharing](./agent-persistent-memory.md#sharing-with-other-agents). While the dialog is open, main canvas undo/redo is deferred so graph editing keeps its own history.

**Filtering the graph.** The top-left of the canvas has a search control, collapsed to a shortcut button until you click it or press **Ctrl/Cmd+F**. It matches an entity's name, its type, and every attribute key and value, as well as a relationship's type (`parent_of`) and its properties; a matched relationship brings both of its entities with it. All whitespace-separated terms must match. A matched entity brings its whole neighbourhood with it — every relationship it takes part in and the entity on the far side of each — so a match is never left as an unconnected dot. A matched relationship brings only the two entities it joins and stops there, since searching a relation type is a question about that relation rather than about everything its ends are attached to. Everything else is hidden outright — not faded — on the canvas and in the **All edges** list, and a badge shows how many of the total entities are left. The **✕** inside the box clears the query first, then closes the box on a second press. Escape unwinds the same way, innermost first: it clears the query, then closes the search box, then leaves the expanded canvas view, and only closes the dialog once none of those are open. Clearing restores the full graph with every entity back where it was.

**Placing entities by hand.** Dragging an entity pins it where you drop it, so the auto-layout settles the rest of the graph around it instead of pulling it back. Dragging the entity you have selected moves its directly connected entities along with it, keeping the cluster's shape; dragging any other entity moves just that one. **Tidy layout** (the wand button) releases every pinned entity and re-runs the auto-layout.

## Extract to Sub-Workflow

Convert selected nodes into a reusable sub-workflow and replace them with an [Execute](../nodes/execute-node.md) node.

### How to Use

1. Select one or more nodes on the canvas
2. Right-click → **Extract to Sub-Workflow**
3. Enter a name (and optional description) for the new workflow
4. Click **Extract**

### What Happens

- A new workflow is created with the selected nodes
- External inputs (edges from outside the selection) become the sub-workflow's [Input](../nodes/input-node.md) fields
- External outputs (edges to nodes outside the selection) are mapped to the sub-workflow's [Output](../nodes/output-node.md)
- The selected nodes are replaced with a single [Execute](../nodes/execute-node.md) node that calls the new workflow
- Input/output mappings are preserved automatically

### Use Cases

- Reuse a sequence of nodes across multiple workflows
- Simplify a complex workflow by grouping related logic
- Create modular, testable sub-workflows

## Run with cURL

The **cURL** button in the editor toolbar (top-right) opens a dialog to build and copy a cURL command for triggering the workflow via API.

- Choose the workflow's request body mode (`Defined` or `Generic`)
- Set the authentication type (Anonymous, JWT, or Header Auth)
- Configure response caching and rate limiting
- Toggle SSE streaming and customize per-node start messages
- Edit the request body
- In Generic mode, the canvas run panel uses the same raw JSON body as the cURL dialog
- Click **Copy cURL** to copy the ready-to-run command

See [Webhooks](./webhooks.md#run-with-curl-dialog) for full dialog details and [SSE Streaming](./sse-streaming.md) for the event protocol.

## Related

- [Keyboard Shortcuts](./keyboard-shortcuts.md) – All canvas and editor shortcuts
- [Agent Persistent Memory](./agent-persistent-memory.md) – Memory graph behavior and API
- [Execute Node](../nodes/execute-node.md) – Calls sub-workflows
- [Expression DSL](./expression-dsl.md) – References and pinned data
- [Workflow Structure](./workflow-structure.md) – Node and edge format
- [Download & Import](./download-import.md) – Export and import workflows as JSON
- [Node Types](./node-types.md) – All node types
- [Logs Tab](../tabs/logs-tab.md) – Docker container logs
- [Execution History](./execution-history.md) – Past runs
- [Templates](../tabs/templates-tab.md) – Save and reuse workflows and nodes
- [Contextual Showcase](./contextual-showcase.md) – Compact page guide available in the editor
