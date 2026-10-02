# Workflow Organization

Heym lets you organize workflows in folders, create sub-folders, and schedule workflows for deletion. See [Workflows Tab](../tabs/workflows-tab.md) for the UI overview.

## Folders and Sub-folders

Folders form a tree. Each folder has:

- **Name** – Display name
- **Parent** – `parent_id` links to another folder; `null` means root
- **Workflows** – Workflows can be moved into folders via `folder_id`

### API

| Endpoint | Purpose |
|----------|---------|
| `GET /folders` | Root folders only |
| `GET /folders/tree` | Full tree (children + workflows) |
| `GET /folders/{id}` | Single folder with contents |
| `POST /folders` | Create folder (`parent_id` optional) |
| `PUT /folders/{id}` | Update name or `parent_id` |
| `DELETE /folders/{id}` | Delete folder (cascade) |
| `PUT /folders/{folder_id}/workflows/{workflow_id}` | Move workflow into folder |
| `DELETE /folders/workflows/{workflow_id}/folder` | Remove workflow from folder |
| `GET /folders/{id}/export` | Download folder + all subfolders as ZIP |

### Tree Structure

The tree response includes `children` and `workflows` per folder. Shared workflows can appear in a folder via `WorkflowShare.folder_id`.

## Sharing Workflows

Open **Share** in the workflow editor to invite users by email or share with a [team](./teams.md). Every invitation and every team share carries a permission:

| Permission | What the collaborator can do |
|------------|------------------------------|
| **Read** | Open the workflow, inspect it, view execution history, and run it. The editor opens in read-only mode: Save is disabled and the canvas cannot be changed. |
| **Write** | Everything Read allows, plus edit the canvas, settings, analysis document, and agent memory. |

The permission is shown next to every entry in the Share dialog and can be changed at any time from that dropdown, without removing and re-adding the share. When a user reaches a workflow through several paths (a direct share and one or more teams), the **highest** permission wins. Shares that existed before permissions were introduced are **Write**, and API clients that omit `permission` also get **Write**.

Owner-only actions never depend on the permission: deleting a workflow, reverting or clearing versions, clearing history, managing shares, and the [owner-only settings](#owner-only-settings) below stay with the owner even for **Write** collaborators. A **Read** collaborator who sends an edit through the API (`PUT /api/workflows/{id}`, the analysis note, agent memory, cache clearing) or through the AI Assistant receives `403` with `You have read-only access to this workflow`.

Sharing a workflow grants access to the canvas, execution history, and analysis document. It does **not** automatically share:

- **Credentials** referenced by nodes in the workflow
- **Sub-workflows** called by [Execute](../nodes/execute-node.md) nodes or agents

Recipients need those credentials and child workflows shared with them separately (same users or teams). Share credentials from the [Credentials tab](../tabs/credentials-tab.md); see [Credentials Sharing](./credentials-sharing.md). Share each sub-workflow from its own editor share dialog.

### Owner-only settings

The whole **Run with cURL** configuration stays with the owner after sharing. Collaborators still open the dialog and copy the generated command, but the controls are read-only.

Changing any of these as a non-owner is rejected with `403`:

- **Authentication** (`auth_type`) and **Header Key** (`auth_header_key`)
- **Request Body** mode (`webhook_body_mode`) and **Request Method** (`http_method`)
- **Response Cache** (`cache_ttl_seconds`) and **Rate Limit** (`rate_limit_requests`, `rate_limit_window_seconds`)
- **SSE Streaming** (`sse_enabled`, `sse_node_config`)

**Header Value** (`auth_header_value`) behaves differently: it is hidden from collaborators entirely, and a collaborator's write is ignored rather than rejected. The editor renders the field masked, so a `403` there would break an ordinary save rather than signal an attack.

Authentication is the reason the block is owner-only: `Anonymous` lets unauthenticated callers run the workflow, and a run with no signed-in caller resolves credentials and global variables as the **owner**, not the caller. The rest of the block is the published request contract and the owner's cost controls, so it moves with it.

**On error, run workflow** (`error_workflow_id`) in the workflow-level **Properties** panel is owner-only for the same reason: the [error workflow](./features.md#error-workflow) runs with the failed run's credentials and global variables, which are the owner's for triggered and anonymous runs. Collaborators see the setting read-only, and adding, replacing, or clearing it as a non-owner is rejected with `403`.

Editing the canvas, name, and description is unaffected.

### Execution tokens

A collaborator can mint an execution token for a workflow shared with them. The run is attributed to **whoever minted the token**, so it uses that user's credentials and global variables, not the owner's. Only a genuinely anonymous call — `auth_type: anonymous` with no caller — runs in the owner's context.

## Scheduled for Deletion

Workflows can be scheduled for deletion instead of being removed immediately.

- **Field**: `scheduled_for_deletion` (nullable datetime)
- **Behavior**: When set, the workflow moves to `folder_id = null` and appears in the "Scheduled for Deletion" section.

### API

| Endpoint | Purpose |
|----------|---------|
| `PUT /workflows/{id}/schedule-deletion` | Set `scheduled_for_deletion`, clear `folder_id` |
| `DELETE /workflows/{id}/schedule-deletion` | Clear `scheduled_for_deletion` (restore) |

### UI

- **Drag to trash** – Drop workflows into the "Scheduled for Deletion" area to schedule them
- **Restore** – Remove from schedule
- **Delete immediately** – Trash icon for permanent removal

### Cleanup Logic

A cron job runs daily at **23:59** (configured timezone). A workflow is only deleted when:

- **All start nodes** (nodes with no incoming edges, excluding sticky/errorHandler) have `active === false`

If any start node is still active, the workflow stays until the next run.

## Dashboard UI

- **Folder rows** – New Folder, recursive folder tree with expand/collapse. Each folder carries an
  optional description under its name and a badge counting the workflows it holds, sub-folders
  included.
- **Folder actions** – New Subfolder, Rename, Change icon, Download as ZIP, and Delete sit inline
  on every folder row; the right-click context menu offers the same set, and phones show a single
  menu button.
- **Main area** – Root workflows (no folder, not scheduled) and Scheduled for Deletion
- **Folder drop preview** – Dragging a workflow highlights the exact folder or sub-folder and
  shows its full path in a card-sized preview. A collapsed folder expands after a short hover.
- **Stable drag feedback** – The source card uses a drag ghost, and the active drop target stays
  selected while scrolling or crossing controls inside the same folder.
- **Destination check** – The current folder is shown as **Already in Folder** and does not accept
  a redundant move.
- **Other drop zones** – Root and "Scheduled for Deletion" highlight when they can accept the
  dragged workflow.
- **ZIP drop** – Drop a ZIP file onto the workflow area to import a folder structure at root level

## Related

- [Workflows Tab](../tabs/workflows-tab.md) – Create and manage workflows
- [Credentials Sharing](./credentials-sharing.md) – Share credentials with workflow collaborators
- [Teams](./teams.md) – Share workflows and credentials with teams
- [Core Concepts](../getting-started/core-concepts.md) – Workflows, nodes, and execution
- [Workflow Structure](./workflow-structure.md) – JSON format for workflows
- [Triggers](./triggers.md) – Start nodes and entry points
