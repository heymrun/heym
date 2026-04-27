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

- **Sidebar** – New Folder, recursive folder tree with expand/collapse
- **Context menu** – New Subfolder, Rename, Download as ZIP, Delete per folder
- **Main area** – Root workflows (no folder, not scheduled) and Scheduled for Deletion
- **Drop zones** – "Drop here to move to root" and "Drop here to schedule for deletion"
- **ZIP drop** – Drop a ZIP file onto the workflow area to import a folder structure at root level

## Related

- [Workflows Tab](../tabs/workflows-tab.md) – Create and manage workflows
- [Core Concepts](../getting-started/core-concepts.md) – Workflows, nodes, and execution
- [Workflow Structure](./workflow-structure.md) – JSON format for workflows
- [Triggers](./triggers.md) – Start nodes and entry points
