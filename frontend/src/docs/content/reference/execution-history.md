# Execution History

Execution history records past workflow runs: inputs, outputs, node results, status, and trigger source. Use it to inspect past runs, debug failures, or re-run with the same inputs via **Bring to Canvas**.

## Overview

Each execution stores:

| Field | Description |
|-------|-------------|
| **Inputs** | Request body or run inputs (e.g. `text` for Input node) |
| **Outputs** | Workflow-level outputs |
| **Node results** | Per-node outputs, status, and execution time |
| **Status** | `success`, `error`, or `pending` |
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

### Use cases

- Re-run a workflow with the same inputs
- Debug a failed run by inspecting inputs and node outputs
- Compare outputs across runs

## Running Executions

Both history dialogs show **currently running executions** at the top of the list, before past runs.

- A spinning indicator and **Running** label appear with the start time
- Click **Cancel** to stop the execution immediately
- Cancelling from any dialog (Editor or Dashboard) also closes the active SSE stream in any open canvas tab for that workflow, so the editor state resets cleanly
- After cancellation, the running entry disappears on the next refresh; press **Refresh** to update the list manually
- If you cancel a run that has already finished, the request is a no-op

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
