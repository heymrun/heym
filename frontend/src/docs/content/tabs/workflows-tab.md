# Workflows Tab

The **Workflows** tab is the default dashboard view. It shows your workflow list, folder structure, and lets you create, edit, and organize workflows.

<video src="/features/showcase/workflows.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/workflows.webm">▶ Watch Workflows demo</a></p>

## Workflow List

- View all workflows in a card grid or list
- Workflows can be in the root or inside folders
- Click a workflow to open it in the [editor](../getting-started/quick-start.md)
- Use **Ctrl+click** (or **Cmd+click**) to open in a new tab
- Pin frequently used workflows in the [Quick Drawer](../reference/quick-drawer.md) so you can run them quickly from the Workflows tab and other internal pages

## Folders

- Organize workflows into [folders and sub-folders](../reference/workflow-organization.md)
- Create folders with the **New Folder** button
- Drag and drop workflows between folders or to the root
- Rename folders from the context menu

## Creating Workflows

1. Click **New Workflow**
2. Enter a name and optional description
3. The workflow opens in the editor

## Import

Drag and drop a JSON workflow file onto the workflow area to create a new workflow. The imported nodes and edges are used to create the workflow; the name comes from the `name` field in the JSON or the filename. See [Download & Import](../reference/download-import.md) for the JSON format and import options.

## Editing and Deleting

- **Edit** – Change workflow name and description from the card menu
- **Delete** – Workflows are [scheduled for deletion](../reference/workflow-organization.md); they move to a trash area before permanent removal

## Command Palette

Press **Ctrl+K** (or **Cmd+K**) to open the command palette. You can:
- Search workflows by name
- Jump to any [dashboard tab](./credentials-tab.md)
- Open recent workflows

## Related

- [Quick Start](../getting-started/quick-start.md) – Build your first workflow
- [Workflow Organization](../reference/workflow-organization.md) – Folders, sub-folders, and scheduled deletion
- [Workflow Structure](../reference/workflow-structure.md) – JSON format for workflows
- [Download & Import](../reference/download-import.md) – Export and import workflows as JSON
- [Portal](../reference/portal.md) – Expose workflows as public chat UIs
- [Core Concepts](../getting-started/core-concepts.md) – Workflows, nodes, and execution
- [Execution History](../reference/execution-history.md) – View past runs and Bring to Canvas
- [Quick Drawer](../reference/quick-drawer.md) – Pin and run workflows from dashboard, docs, and other non-editor pages
- [Contextual Showcase](../reference/contextual-showcase.md) – Short page guide for dashboard surfaces
