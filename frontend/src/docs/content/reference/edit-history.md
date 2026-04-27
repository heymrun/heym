# Edit History

Edit History tracks saved versions of a workflow. Use it to view changes over time, compare versions, or revert to a previous state.

**Note:** Edit History is different from [Execution History](./execution-history.md). Edit History tracks **saves** (workflow structure changes); Execution History tracks **runs** (past executions).

## Where to Find It

**Editor toolbar** → **Edit History** (GitBranch icon)

## Versions

A new version is created each time you **Save** the workflow. The list shows:

- **Current** – The latest saved state (what you see on the canvas)
- **Version N** – Past saves with timestamps

Versions with no changes compared to the previous one are hidden.

## Diff View

Select a version to see what changed compared to the current workflow:

| Change Type | Description |
|-------------|--------------|
| **Nodes** | Added, removed, or modified nodes |
| **Edges** | Added, removed, or modified connections |
| **Config** | Workflow-level settings (auth, rate limits, etc.) |

Expand each change to see field-level diffs (e.g. which node properties changed).

## Preview

To see what the workflow looked like at a past version, click **Preview** next to Revert.

A read-only canvas opens showing the nodes and edges of that version. You can pan and zoom to explore the layout; no changes can be made from this view.

## Revert

To restore a past version:

1. Select the version you want
2. Click **Revert**
3. Confirm the action
4. The current workflow is replaced with the selected version; the page reloads

Reverting creates a new "current" state—you can revert again if needed.

## Clear History

Click the trash icon in the dialog header to remove all version history. This action cannot be undone. The current workflow remains; only past versions are deleted.

## When Versions Are Created

Versions are created only when you **Save** (Ctrl/Cmd+S or the Save button). Unsaved changes are not stored in Edit History until you save.

## Related

- [Execution History](./execution-history.md) – Past runs and Bring to Canvas
- [Workflow Structure](./workflow-structure.md) – Node and edge format
- [Workflows Tab](../tabs/workflows-tab.md) – Create and manage workflows
