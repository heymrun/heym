# Templates Tab

The Templates tab lets you save, browse, and reuse complete workflows and individual nodes. Share something you built once and apply it to new projects in one click.

<video src="/features/showcase/templates.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/templates.webm">▶ Watch Templates demo</a></p>

## Overview

There are two kinds of templates:

- **Workflow templates** — save a complete workflow (all nodes and connections) as a reusable starting point.
- **Node templates** — save a single configured node (e.g. a tuned LLM node or a custom HTTP node) for reuse across different workflows.

Switch between the two using the **Workflows / Nodes** toggle at the top of the tab.

Use the search bar to filter the visible templates by name, description, tags, or node type.

---

## Creating a Template

### Workflow template

1. Open the workflow you want to share in the editor.
2. Click **Share as Template** in the top toolbar.
3. Fill in name, description, and optional tags.
4. Choose visibility: **Everyone** (all users) or **Specific users** (enter usernames and/or select teams).
5. Click **Share**. A green notification confirms success.

### Node template

1. Right-click any node on the canvas.
2. Select **Share as Template** from the context menu.
3. Fill in the form and click **Share**.

---

## Using a Template

### Workflow template

1. Open the **Templates** tab and make sure **Workflows** is selected.
2. Click a card to preview it, or click **Use** directly.
3. The workflow is cloned into a new workflow that opens in the editor.

### Node template

1. Open the **Templates** tab and select **Nodes**.
2. Click **Use** on a node template card.
3. A dialog appears — choose where to add the node:
   - **New workflow** — creates a fresh workflow containing only this node.
   - **Existing workflow** — pick from your workflow list; the node is inserted automatically when the editor opens.

---

## Preview

Click any template card to open a full preview:

- **Card thumbnails** — template cards render a fitted read-only canvas snapshot for both workflows and single-node templates.
- **Workflow templates** — a read-only canvas that matches the edit-history preview style, including pan and zoom.
- **Node templates** — the saved node opens on the same read-only canvas as a single-node preview.
- **Node details** — click any node in the preview to inspect its saved configuration in the side panel.
- Tags, use count, and **owner** are shown for all templates.

Press **ESC** or click outside to close the preview.

---

## Managing Templates

- **Edit** – If you are the template owner, hover the card and click the pencil icon to update its name, description, tags, or visibility
- **Delete** – If you are the template owner, hover the card and delete the template after the confirmation prompt
- **Owner-only actions** – Edit and delete controls are shown only for templates you created

---

## Command Palette (CTRL+K)

Templates (both workflow and node) are searchable from the **CTRL+K** command palette. Select a template to use it immediately — workflow templates open in the editor, node templates prompt for a destination.

---

## Templates in Chat

You can ask the AI questions about your templates — it knows all templates in your workspace.

---

## Visibility

| Setting | Who can see it |
|---|---|
| Everyone | All users on the platform |
| Specific users | Users you list by name and/or teams you select — all team members gain access |

When sharing with **Specific users**, you can add both individual users (by name) and teams. Team members see the template in the Templates tab and can use it.

---

## Related

- [Teams](../reference/teams.md) – Share templates with teams
- [Canvas Features](../reference/canvas-features.md)
- [Workflow Structure](../reference/workflow-structure.md)
- [Node Types](../reference/node-types.md)
- [Chat Tab](./chat-tab.md)
- [Contextual Showcase](../reference/contextual-showcase.md) – Short page guide for dashboard tabs
