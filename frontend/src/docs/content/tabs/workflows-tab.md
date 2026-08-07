# Workflows Tab

The **Workflows** tab is the default dashboard view. It shows your workflow list, folder structure, and lets you create, edit, and organize workflows.

<video src="/features/showcase/workflows.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/workflows.webm">▶ Watch Workflows demo</a></p>

## Start a Chat

Above the workflow list there is a chat box that greets you by name and asks what you want to automate. Type a prompt, optionally attach one file, and pick the credential and model you want. Both dropdowns are searchable and start on your [AI defaults](../reference/user-settings.md).

Sending creates a new conversation and opens it in the [Chat tab](./chat-tab.md), where the reply streams in. Supported attachments are text files, images, and PDFs, one per message, same as the chat composer.

If you have no LLM credential yet, the box shows a link to the [Credentials tab](./credentials-tab.md) and sending stays disabled.

Click the **x** to hide the box. An **Ask AI** button then appears next to the Workflows heading and brings it back. The choice is remembered in your browser.

## Workflow List

- View all workflows in a card grid or list
- Workflows can be in the root or inside folders
- Click a workflow to open it in the [editor](../getting-started/quick-start.md)
- Use **Ctrl+click** (or **Cmd+click**) to open in a new tab
- Pin frequently used workflows in the [Quick Drawer](../reference/quick-drawer.md) so you can run them quickly from the Workflows tab and other internal pages

## Active Workflows

On desktop, the circular badge in the top toolbar shows how many workflows are currently
running and refreshes automatically every 10 seconds. Click a non-zero badge to open the active
workflow list, which shows up to four rows before scrolling. Select a workflow name to attach the
editor to that run's live view. The zero badge is informational and cannot be opened, and the
badge is hidden on mobile screens.

## Search

Use the workflow search field beside **New Folder**, or press **Ctrl+F** (or **Cmd+F**), to filter workflows by title or description. Matching workflows inside folders are shown with their folder branches expanded. Press **Escape** to clear the search.

## Folders

- Organize workflows into [folders and sub-folders](../reference/workflow-organization.md)
- Create folders with the **New Folder** button
- Drag a workflow over a folder or sub-folder to see a card-sized destination preview. The
  highlighted preview shows the full folder path before you drop, and hovering a collapsed
  folder briefly expands it so you can reach nested folders.
- Drag workflows between folders or to the root. The dragged card stays visible as a ghost,
  and the active destination remains highlighted while you scroll.
- Dropping a workflow back into its current folder is disabled and marked **Already in Folder**.
- Rename folders from the context menu

## Creating Workflows

1. Click **New Workflow**
2. Enter a name and optional description
3. The workflow opens in the editor

## Import

Drag and drop a JSON workflow file onto the workflow area to create a new workflow. The imported nodes and edges are used to create the workflow; the name comes from the `name` field in the JSON or the filename. See [Download & Import](../reference/download-import.md) for the JSON format and import options.

## Sharing

Open a workflow in the editor and click **Share** to invite users by email or share with a [team](./teams-tab.md). Shared collaborators can view, edit, and run the workflow. Credentials and sub-workflows are not shared automatically; share those separately with the same users or teams. See [Workflow Organization](../reference/workflow-organization.md#sharing-workflows) and [Credentials Sharing](../reference/credentials-sharing.md).

## Editing and Deleting

- **Edit** – Change workflow name and description from the card menu
- **Delete** – Workflows are [scheduled for deletion](../reference/workflow-organization.md); they move to a trash area before permanent removal

## Concurrent Edits

Saving sends the revision your edits are based on, and the server rejects the write if the workflow changed in the meantime — for example because a teammate saved it, or you left the same workflow open in a second tab. Heym then shows a **Stale Workflow Detected** dialog with two choices:

- **Cancel** – Keeps your unsaved changes in the editor so you can reload in another tab and reconcile them
- **Override** – Saves anyway, replacing the other person's version

**Running** a workflow saves it first, so it goes through the same check. If the workflow changed underneath you, the run pauses on the dialog rather than overwriting silently: **Override and Run** saves your version and starts the run, **Cancel Run** abandons both and leaves your edits untouched.

The check is part of the save request itself, so it costs no extra round trip and there is no window in which a save could slip past it. Your own changes from elsewhere in the app — a rename, a settings change, a properties-panel toggle — never count as a conflict.

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
- [Board](./board-tab.md) – Run workflows from kanban cards via column chains
- [Core Concepts](../getting-started/core-concepts.md) – Workflows, nodes, and execution
- [Execution History](../reference/execution-history.md) – View past runs and Bring to Canvas
- [Quick Drawer](../reference/quick-drawer.md) – Pin and run workflows from dashboard, docs, and other non-editor pages
- [Contextual Showcase](../reference/contextual-showcase.md) – Short page guide for dashboard surfaces
