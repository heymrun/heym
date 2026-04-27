# Folder ZIP Export & Import

**Date:** 2026-04-06

## Overview

Two related features:
1. Export a folder (with all subfolders and workflows) as a ZIP file via the 3-dot context menu on the homepage.
2. Import a ZIP file by dropping it onto the workflow list — recreates the folder structure and all workflows at root level.

## Approach

- **Export:** Backend generates the ZIP (single HTTP request, Python stdlib `zipfile`, no new dependencies).
- **Import:** Client-side ZIP parsing with `JSZip`, consistent with the existing single-workflow JSON drop-to-import pattern.

---

## ZIP Format

The ZIP mirrors the folder hierarchy as directories:

```
FolderName/
  workflow1.json
  workflow2.json
  SubFolder/
    workflow3.json
    DeepSub/
      workflow4.json
```

Each `.json` file contains `{ name, nodes, edges }` — the same shape as single-workflow JSON export/import.

---

## Backend

### New endpoint

```
GET /folders/{folder_id}/export
Authorization: Bearer <token>
→ 200 application/zip
→ Content-Disposition: attachment; filename="<FolderName>.zip"
```

**Implementation** (`backend/app/api/folders.py`):

- Fetch the folder tree recursively from DB (reuse `_get_all_descendant_ids` pattern).
- For each folder, load its workflows (nodes + edges).
- Build the ZIP in-memory using `zipfile.ZipFile` (stdlib).
- Path inside ZIP: `FolderName/SubFolder/workflow.json` (sanitize slashes in names).
- Return as `StreamingResponse` with `application/zip` content type.
- 404 if folder not found or not owned by current user.

---

## Frontend — Export

### API client (`frontend/src/services/api.ts`)

Add to `folderApi`:

```ts
exportZip: async (id: string): Promise<Blob> => {
  const response = await api.get(`/folders/${id}/export`, { responseType: "blob" });
  return response.data;
}
```

### Context menu (`DashboardView.vue`)

Add "Download as ZIP" between Rename and the Delete separator:

```
[ New Subfolder ]
[ Rename        ]
──────────────────
[ Download ZIP  ]   ← new (Download icon from lucide-vue-next)
──────────────────
[ Delete        ]
```

Handler:

```ts
async function downloadFolderAsZip(folder: FolderTree): Promise<void> {
  const blob = await folderApi.exportZip(folder.id);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${folder.name}.zip`;
  a.click();
  URL.revokeObjectURL(url);
}
```

---

## Frontend — Import

### Dependency

```
npm install jszip
```

(`@types/jszip` not needed — JSZip ships its own types.)

### Drag overlay text

Update the existing drop zone label from:
> "Drop JSON to import workflow"

to:
> "Drop JSON or ZIP to import"

Also update `handleJsonDragOver` to accept `.zip` files alongside `.json`.

### Handler logic (`handleJsonDrop` extension)

When the dropped file is a `.zip`:

1. Load with `JSZip.loadAsync(file)`.
2. Group entries by directory path to reconstruct the folder tree.
3. Create folders top-down via `folderApi.create()`, tracking `name → id` map.
4. For each `.json` entry:
   - Parse `{ name, nodes, edges }`.
   - Run `sanitizeImportedNode` on each node (credential/workflow-ref cleanup).
   - `workflowApi.create({ name, description })` → get new ID.
   - `workflowApi.update(id, { nodes, edges })`.
   - `folderApi.moveWorkflowToFolder(folderId, workflowId)`.
5. If a single workflow fails, log and continue; show a summary toast at the end:
   > "5/6 workflows imported successfully" or "Folder imported successfully"

### Error handling

- Non-ZIP, non-JSON file → toast "Please drop a JSON or ZIP file".
- ZIP with no `.json` files → toast "No workflows found in ZIP".
- Partial failure → continue importing remaining workflows, report count in toast.

---

---

## Documentation Updates

### `frontend/src/docs/content/reference/download-import.md`

Add a new **Folder ZIP** section covering:
- How to download a folder as ZIP via the context menu (3-dot → Download as ZIP)
- ZIP format: mirrors the folder/subfolder hierarchy as directories, each workflow as `{name}.json`
- How to import a ZIP by dropping it onto the workflow area (same drop zone as JSON import)
- Error handling: partial failure reports count (e.g. "5/6 workflows imported")

Update the existing **Import → From Dashboard** section to mention ZIP files alongside JSON.

Update the **JSON Format** section title to **File Formats** and add the ZIP format description.

Update the **Use Cases** section to include folder-level backup and migration.

### `frontend/src/docs/content/reference/workflow-organization.md`

- Add `GET /folders/{id}/export` to the API table under Folders.
- Update **Context menu** bullet under Dashboard UI to mention "Download as ZIP".
- Add a note under **Dashboard UI** that the drop zone accepts ZIP files for folder import.

---

## Out of Scope

- Importing ZIP into a specific target folder (always creates at root).
- Exporting workflows outside of folders as ZIP.
- Server-side ZIP import endpoint.
