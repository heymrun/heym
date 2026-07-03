# Execution History

Execution history records past workflow runs: inputs, outputs, node results, status, and trigger source. Use it to inspect past runs, debug failures, or re-run with the same inputs via **Bring to Canvas**.

## Overview

Each execution stores:

| Field | Description |
|-------|-------------|
| **Inputs** | Request body or run inputs (e.g. `text` for Input node) |
| **Outputs** | Workflow-level outputs |
| **Node results** | Per-node outputs, status, and execution time |
| **Status** | `success`, `error`, `pending`, `skipped`, or `failed` (see [Crash Recovery](#crash-recovery)) |
| **trigger_source** | How the run was triggered (see [Triggers](./triggers.md)) |

## Accessing History

| Location | Scope |
|----------|-------|
| **Editor** toolbar | Current workflow only |
| **Docs** view header | Current workflow only |
| **Dashboard** header (Chat tab) | All workflows + chat/assistant runs |
| **Evals** view header | All workflows + chat/assistant runs |

Click the **History** button (clock icon) to open the dialog.

## Per-workflow vs All History

- **Per-workflow** (Editor, Docs): Shows runs for the workflow you have open. Use **Clear history** to remove runs for that workflow only.
- **All History** (Dashboard, Evals): Shows runs across all workflows and chat/assistant sessions. Use **Clear all history** to remove everything.

## Bring to Canvas

**Bring to Canvas** loads a selected run's inputs and node outputs into the current workflow.

### What it loads

- **Inputs** → Run input panel (e.g. `text` for Input node, or custom fields)
- **Node results** → Execution result panel shows past outputs per node
- **Execution result** → Status, outputs, and timing from the run

### Behavior by context

- **In Editor** (per-workflow history): Applies immediately to the open workflow and closes the dialog.
- **From All History** (Dashboard/Evals): Navigates to the workflow editor, then applies the data when the editor loads. Only available for workflow runs—not for chat/assistant runs.

### Execution deep link

Opening a workflow at `/workflows/{workflowId}/{executionId}` automatically brings that execution onto the canvas — the same as selecting the run and choosing **Bring to Canvas**. This makes a specific past run shareable as a URL. If the execution can't be found (wrong or deleted id), the editor falls back to loading the plain workflow.

### Use cases

- Re-run a workflow with the same inputs
- Debug a failed run by inspecting inputs and node outputs
- Compare outputs across runs

## Execution Highlights

After a live run — or after **Bring to Canvas** — a dismissible **Execution Highlights** popup appears in the **top-right of the Canvas**. It's a quick way to see *what each node produced*, listed top-to-bottom in execution order. Close it with the **✕**; it reopens on the next run.

### What's shown

| Record | Source | Auto? |
|--------|--------|-------|
| **Input** | The run's input parameters (input/trigger node) | Yes |
| **Output** | The output node's result — or, if there is none, the last node's message | Yes |
| **Agent / LLM** | Each agent or LLM node's output | Yes |
| **Output** | Any other node with **Highlight Node Output** enabled | Opt-in |

Nodes that are already auto-highlighted (input / output / last / agent / llm) never appear twice, even if you also enable the toggle.

### Each record

- Shows `Node — message…` with the first **250 characters**; click a row to expand it and render the **full message as Markdown**, with a **Copy** button.
- A node that ran multiple times (e.g. inside a loop) shows `Node (N)` with a `‹ i / N ›` selector — pick which run to view; each node's selector is independent.

### Highlight Node Output

Every node **except Agent and LLM** has a **Highlight Node Output** checkbox in its properties panel (default off). Enable it to add that node's output to the popup. A small ✦ badge appears on highlighted nodes on the canvas. In the [workflow DSL](./expression-dsl.md) this is the node-data field `"highlight": true` (defaults to `false`).

### On dashboards

Dashboard widget cards that ran a workflow show a ✦ **Execution highlights** button in the card header; click it to open the same popup for that widget's run, with the widget's drawn output as the prominent record.

## Running Executions

Both history dialogs show **currently running executions** at the top of the list, before past runs.

- A spinning indicator and **Running** label appear with the start time
- Click **Cancel** to stop the execution immediately
- Cancelling from any dialog (Editor or Dashboard) also closes the active SSE stream in any open canvas tab for that workflow, so the editor state resets cleanly
- After cancellation, the running entry disappears on the next refresh; press **Refresh** to update the list manually
- If you cancel a run that has already finished, the request is a no-op

## Crash Recovery

If the server restarts (deploy, container restart, or crash) while a workflow is running, that run's worker stops mid-execution. Heym automatically recovers these interrupted runs instead of leaving them stuck as **Running**.

- On the next startup, the elected leader process detects orphaned runs — instantly for a graceful restart, or within ~60 seconds for a hard crash (once heartbeats clearly stop).
- Recovered runs are **re-run from scratch with the same inputs** (not resumed from where they stopped), using the current workflow definition. On completion they record a normal terminal entry (e.g. `success`), so history shows the run as completed.
- A run is retried **once**. If the recovery attempt is also interrupted — or the workflow has since been deleted — the entry is recorded as `failed`.
- This works the same across a single container and multi-worker deployments; only the leader performs recovery, so a run is never recovered twice by different workers.

### Auto-recover toggle

The editor **Execution Log** (run) panel has an **Auto-recover** checkbox, **on by default** per workflow.

- **On**: interrupted runs of this workflow are re-run as described above.
- **Off**: interrupted runs are not re-run and are recorded with status `skipped`.

> Sub-workflow runs are not recovered independently — they are re-driven by their recovered parent run. Triggers with their own redelivery (RabbitMQ, scheduled/cron, IMAP) may also redeliver on restart, so a recovered run can occasionally execute twice.

## Pending Human Review

Runs that pause for [Human-in-the-Loop](./human-in-the-loop.md) approval are written to history immediately with status `pending`.

- The pending agent node stores a review payload including `reviewUrl`, `draftText`, and `expiresAt`
- Any nodes connected to the agent's `review` handle can also run before the human responds, and their node results are stored in the same pending history entry
- History dialogs show the review link so owners can copy or open it
- History dialogs and the editor Debug panel show the final human decision after the run resumes
- When a reviewer accepts, edits, or refuses the draft, the same history entry is updated with the final execution result
- If the same run pauses for HITL more than once, the history entry stays the same while each checkpoint gets its own one-time review link

This is especially useful for portal runs and long-lived workflows that may wait hours or days before continuing.

## Copy

Use **Copy** next to Inputs or Outputs to copy the JSON to the clipboard.

## Clear History

- **Per-workflow**: In the Editor history dialog, click **Clear history** to remove runs for the current workflow.
- **All History**: In the Dashboard/Evals history dialog, click **Clear all history** to remove all execution records. This action cannot be undone.

## Related

- [Triggers](./triggers.md) – How workflows are started; history records `trigger_source`
- [Human-in-the-Loop](./human-in-the-loop.md) – Pending review URLs and resume behavior
- [Edit History](./edit-history.md) – Version control for workflow saves (revert, diff)
- [Quick Start](../getting-started/quick-start.md) – Build and run your first workflow
- [Workflows Tab](../tabs/workflows-tab.md) – Create and manage workflows
