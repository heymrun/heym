# Workflow Analysis

**Workflow Analysis** is a left-side panel that holds one shared, editable Markdown document per workflow. Use it to explain what a workflow does and to capture improvement ideas — and let AI generate a first draft for you.

The document is shared: everyone who can access the workflow can read and edit it. It is stored with the workflow and deleted automatically when the workflow is deleted.

## Opening the Panel

1. Open a workflow in the editor.
2. Click **Analyze** (Sparkles icon) in the editor toolbar.
3. The panel opens on the left. The node palette (left panel) collapses while it is open; reopening the node palette closes the analysis panel.

The panel is only available for saved workflows. On a brand-new unsaved workflow, save it first.

## The Document

The panel shows a single Markdown document with two views, toggled by the **Edit** (pencil) and **Preview** (eye) buttons:

| View | Purpose |
|------|---------|
| **Edit** | Plain Markdown editor (textarea). |
| **Preview** | Rendered Markdown. |

The header shows **who last edited** the document and when.

### Saving

Click **Save** to persist your changes. Save is enabled only when there are unsaved edits.

Because the document is shared, saves use optimistic concurrency:

- If someone else saved a newer version since you opened the panel, your save is rejected and a warning appears naming the other editor.
- You can then choose **Reload (discard mine)** to take the server version, or **Overwrite** to force-save your version over theirs.

## AI Analysis

Select an LLM **Credential** and **Model** at the top of the panel (the model list loads from the selected credential — see [Credentials](../tabs/credentials-tab.md)). Then run the analysis:

- **Analyze my workflow** — shown when the document is empty. It streams an AI-generated Markdown report directly into the editor as an unsaved draft. Review and edit it, then **Save**.
- **Reanalyze** — shown when the document already has content. It streams a fresh report into a separate **preview**, leaving your current document untouched. Choose **Accept** to replace the editor content with the new analysis, or **Discard** to keep what you had.

Both actions first **run the workflow** (when it is valid and runnable) and include the execution results in the analysis prompt, so the report reflects how the workflow actually behaves. If the workflow can't run, the analysis proceeds from its static structure instead.

The generated report covers three sections, in order: **Improvement areas** (concrete suggestions, including a **security** angle whenever the workflow touches credentials, user input, external requests, or data exposure), the workflow's **Purpose**, and **What it does** (a step-by-step walk through the nodes).

Each analysis run is recorded in [Traces](../tabs/traces-tab.md) under the **Workflow Analysis** source.

If no LLM credential is configured, the Analyze button is disabled — add one in the [Credentials Tab](../tabs/credentials-tab.md).

## Related

- [AI Assistant](./ai-assistant.md) — generate or modify workflow nodes from natural language.
- [Sticky Note](../nodes/sticky-note-node.md) — for short notes pinned directly on the canvas.
