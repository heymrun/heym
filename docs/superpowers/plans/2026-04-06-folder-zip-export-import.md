# Folder ZIP Export & Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Download as ZIP" to the folder context menu and allow dropping a ZIP onto the workflow list to re-import the folder structure and all its workflows.

**Architecture:** Backend streams a ZIP built with Python's stdlib `zipfile` (no new deps). Frontend triggers the download via a blob URL. ZIP import is client-side using the already-installed `jszip` package, calling existing folder/workflow API endpoints in sequence.

**Tech Stack:** FastAPI (Python stdlib `zipfile`, `io`), Vue 3, TypeScript, jszip (already in `package.json`)

---

## File Map

| File | Change |
|------|--------|
| `backend/app/api/folders.py` | Add `GET /folders/{folder_id}/export` endpoint + `_build_zip_bytes` helper |
| `backend/tests/test_folder_export.py` | New — unit tests for `_build_zip_bytes` |
| `frontend/src/services/api.ts` | Add `exportZip` method to `folderApi` |
| `frontend/src/views/DashboardView.vue` | Add Download icon import, `folderApi` import, `downloadFolderAsZip`, extend drag/drop for ZIP, update context menu and overlay text |
| `frontend/src/docs/content/reference/download-import.md` | Document ZIP export/import |
| `frontend/src/docs/content/reference/workflow-organization.md` | Document new API endpoint + context menu option |

---

## Task 1: Backend — ZIP builder helper + unit tests

**Files:**
- Modify: `backend/app/api/folders.py`
- Create: `backend/tests/test_folder_export.py`

- [ ] **Step 1: Add `_build_zip_bytes` helper to `folders.py`**

Add this function after the existing `_get_first_node_type` helper (around line 51):

```python
import io
import json
import zipfile


def _build_zip_bytes(
    folder_name: str,
    workflows: list[dict],
    children: list[dict],
    prefix: str = "",
) -> bytes:
    """
    Recursively build a ZIP archive in-memory.

    `workflows` entries: {"name": str, "nodes": list, "edges": list}
    `children` entries: {"name": str, "workflows": list[dict], "children": list[dict]}
    Returns raw ZIP bytes.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        _write_folder_to_zip(zf, folder_name, workflows, children, prefix)
    return buf.getvalue()


def _write_folder_to_zip(
    zf: zipfile.ZipFile,
    folder_name: str,
    workflows: list[dict],
    children: list[dict],
    prefix: str,
) -> None:
    safe_name = folder_name.replace("/", "_").replace("\\", "_")
    folder_path = f"{prefix}{safe_name}/"

    for wf in workflows:
        safe_wf_name = wf["name"].replace("/", "_").replace("\\", "_")
        content = json.dumps(
            {"name": wf["name"], "nodes": wf["nodes"], "edges": wf["edges"]},
            ensure_ascii=False,
        ).encode("utf-8")
        zf.writestr(f"{folder_path}{safe_wf_name}.json", content)

    for child in children:
        _write_folder_to_zip(
            zf,
            child["name"],
            child["workflows"],
            child["children"],
            folder_path,
        )
```

Also add `import io` and `import json` and `import zipfile` at the top of the file (after existing imports).

- [ ] **Step 2: Write failing tests for `_build_zip_bytes`**

Create `backend/tests/test_folder_export.py`:

```python
import io
import json
import unittest
import zipfile

from app.api.folders import _build_zip_bytes


class BuildZipBytesTests(unittest.TestCase):
    def _load_zip(self, data: bytes) -> dict[str, bytes]:
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf) as zf:
            return {name: zf.read(name) for name in zf.namelist()}

    def test_single_folder_single_workflow(self) -> None:
        data = _build_zip_bytes(
            folder_name="MyFolder",
            workflows=[{"name": "WF1", "nodes": [{"id": "n1"}], "edges": []}],
            children=[],
        )
        files = self._load_zip(data)
        self.assertIn("MyFolder/WF1.json", files)
        payload = json.loads(files["MyFolder/WF1.json"])
        self.assertEqual(payload["name"], "WF1")
        self.assertEqual(payload["nodes"], [{"id": "n1"}])
        self.assertEqual(payload["edges"], [])

    def test_nested_subfolder(self) -> None:
        data = _build_zip_bytes(
            folder_name="Root",
            workflows=[],
            children=[
                {
                    "name": "Child",
                    "workflows": [{"name": "WF2", "nodes": [], "edges": []}],
                    "children": [],
                }
            ],
        )
        files = self._load_zip(data)
        self.assertIn("Root/Child/WF2.json", files)

    def test_slash_in_name_is_sanitized(self) -> None:
        data = _build_zip_bytes(
            folder_name="My/Folder",
            workflows=[{"name": "A/B", "nodes": [], "edges": []}],
            children=[],
        )
        files = self._load_zip(data)
        self.assertIn("My_Folder/A_B.json", files)

    def test_empty_folder_produces_valid_zip(self) -> None:
        data = _build_zip_bytes(
            folder_name="Empty",
            workflows=[],
            children=[],
        )
        files = self._load_zip(data)
        self.assertEqual(files, {})

    def test_multiple_workflows_in_folder(self) -> None:
        data = _build_zip_bytes(
            folder_name="Multi",
            workflows=[
                {"name": "Alpha", "nodes": [], "edges": []},
                {"name": "Beta", "nodes": [], "edges": []},
            ],
            children=[],
        )
        files = self._load_zip(data)
        self.assertIn("Multi/Alpha.json", files)
        self.assertIn("Multi/Beta.json", files)
```

- [ ] **Step 3: Run tests to verify they fail (function not yet imported)**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend
python -m pytest tests/test_folder_export.py -v
```

Expected: ImportError or NameError — `_build_zip_bytes` not yet defined.

- [ ] **Step 4: Add the helper code from Step 1, run tests again**

```bash
python -m pytest tests/test_folder_export.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/folders.py backend/tests/test_folder_export.py
git commit -m "feat: add _build_zip_bytes helper with tests"
```

---

## Task 2: Backend — Export endpoint

**Files:**
- Modify: `backend/app/api/folders.py`

- [ ] **Step 1: Add the export endpoint**

Add this after `_build_zip_bytes` / before the `@router.get("")` route (or at the end before the workflow-move routes). Add `StreamingResponse` to FastAPI imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
```

Then add the endpoint:

```python
@router.get("/{folder_id}/export")
async def export_folder_as_zip(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    result = await db.execute(
        select(Folder)
        .where(Folder.id == folder_id)
        .where(Folder.owner_id == current_user.id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    async def _load_folder_dict(f: Folder) -> dict:
        wf_result = await db.execute(
            select(Workflow).where(Workflow.folder_id == f.id)
        )
        workflows = list(wf_result.scalars().all())

        children_result = await db.execute(
            select(Folder)
            .where(Folder.parent_id == f.id)
            .where(Folder.owner_id == current_user.id)
            .order_by(Folder.name)
        )
        children = list(children_result.scalars().all())

        return {
            "name": f.name,
            "workflows": [
                {"name": w.name, "nodes": w.nodes or [], "edges": w.edges or []}
                for w in workflows
            ],
            "children": [await _load_folder_dict(c) for c in children],
        }

    folder_dict = await _load_folder_dict(folder)
    zip_bytes = _build_zip_bytes(
        folder_name=folder_dict["name"],
        workflows=folder_dict["workflows"],
        children=folder_dict["children"],
    )

    safe_filename = folder.name.replace('"', "").replace("/", "_")
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}.zip"'},
    )
```

- [ ] **Step 2: Verify the route ordering doesn't conflict**

The route `/{folder_id}/export` must be placed **after** `/workflows/{workflow_id}/folder` and **before** `/{folder_id}` (GET) in the file, OR use a more specific path. Actually FastAPI matches by order, so `/{folder_id}/export` needs to come before `/{folder_id}` to avoid "export" being interpreted as a folder ID. Confirm placement in the file: put it **before** `@router.get("/{folder_id}", ...)`.

Run the backend to check for startup errors:

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend
python -c "from app.api.folders import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/folders.py
git commit -m "feat: add GET /folders/{id}/export endpoint"
```

---

## Task 3: Frontend API client — `exportZip`

**Files:**
- Modify: `frontend/src/services/api.ts` (around line 672, end of `folderApi`)

- [ ] **Step 1: Add `exportZip` to `folderApi`**

In `frontend/src/services/api.ts`, find the `folderApi` object. Add `exportZip` before the closing `};`:

```ts
  exportZip: async (id: string): Promise<Blob> => {
    const response = await api.get(`/folders/${id}/export`, { responseType: "blob" });
    return response.data as Blob;
  },
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: add folderApi.exportZip client method"
```

---

## Task 4: Frontend — "Download as ZIP" context menu option

**Files:**
- Modify: `frontend/src/views/DashboardView.vue`

- [ ] **Step 1: Add `Download` icon and `folderApi` imports**

At the top of `DashboardView.vue`, add `Download` to the lucide imports (line 4–21 block):

```ts
import {
  AlertTriangle,
  Check,
  Clock,
  Copy,
  Download,   // ← add this
  Edit2,
  FileJson,
  FolderPlus,
  History,
  LayoutTemplate,
  Pin,
  Plus,
  RotateCcw,
  Settings,
  Trash2,
  Workflow,
  X,
} from "lucide-vue-next";
```

Also add `folderApi` to the services import (line 56):

```ts
import { credentialsApi, folderApi, templatesApi, workflowApi } from "@/services/api";
```

- [ ] **Step 2: Add `downloadFolderAsZip` function**

Add this function after `openContextMenu` (around line 692):

```ts
async function downloadFolderAsZip(folder: FolderTree): Promise<void> {
  try {
    const blob = await folderApi.exportZip(folder.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${folder.name}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch {
    showToast("Failed to download folder");
  }
}
```

- [ ] **Step 3: Add "Download as ZIP" button to context menu**

Find the context menu in the template (around line 1759). Add between the Rename button and the delete separator:

```html
<button
  class="w-full px-3 py-2 text-sm text-left flex items-center gap-2 hover:bg-accent/50 rounded-lg mx-1 transition-colors"
  style="width: calc(100% - 8px)"
  @click="downloadFolderAsZip(contextMenuFolder); showContextMenu = false"
>
  <Download class="w-4 h-4" />
  Download as ZIP
</button>
```

Place it so the final menu reads:

```
[ New Subfolder ]
[ Rename        ]
──────────────────
[ Download ZIP  ]
──────────────────
[ Delete        ]
```

Add `<div class="border-t border-border/50 my-1.5" />` before Download if there isn't one already.

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/DashboardView.vue
git commit -m "feat: add Download as ZIP to folder context menu"
```

---

## Task 5: Frontend — ZIP import via drag & drop

**Files:**
- Modify: `frontend/src/views/DashboardView.vue`

- [ ] **Step 1: Add JSZip import**

At the top of `DashboardView.vue` script block, add:

```ts
import JSZip from "jszip";
```

- [ ] **Step 2: Update `handleJsonDragOver` to accept ZIP files**

Find `handleJsonDragOver` (around line 698). Update the file-type check:

```ts
function handleJsonDragOver(event: DragEvent): void {
  event.preventDefault();
  if (event.dataTransfer) {
    const items = event.dataTransfer.items;
    if (items && items.length > 0 && items[0].kind === "file") {
      isDraggingJsonFile.value = true;
      event.dataTransfer.dropEffect = "copy";
    }
  }
}
```

(No change needed here — it already accepts any file kind. The filter happens in `handleJsonDrop`.)

- [ ] **Step 3: Update overlay text**

Find the drop overlay in the template (around line 1050):

```html
<span class="text-lg font-medium">Drop JSON to import workflow</span>
```

Change to:

```html
<span class="text-lg font-medium">Drop JSON or ZIP to import</span>
```

- [ ] **Step 4: Add `importZipFile` function**

Add this function after `handleJsonDrop` (around line 866):

```ts
async function importZipFile(file: File): Promise<void> {
  let zip: JSZip;
  try {
    zip = await JSZip.loadAsync(file);
  } catch {
    showToast("Invalid ZIP file");
    return;
  }

  // Collect all .json entries
  const jsonFiles: { path: string; content: string }[] = [];
  const promises: Promise<void>[] = [];

  zip.forEach((relativePath, entry) => {
    if (!entry.dir && relativePath.endsWith(".json")) {
      promises.push(
        entry.async("string").then((content) => {
          jsonFiles.push({ path: relativePath, content });
        }),
      );
    }
  });

  await Promise.all(promises);

  if (jsonFiles.length === 0) {
    showToast("No workflows found in ZIP");
    return;
  }

  // Build folder path → folder id map, create folders top-down
  const folderIdMap = new Map<string, string>(); // "FolderA/SubB" → uuid

  // Collect unique folder paths (all directory segments)
  const allFolderPaths = new Set<string>();
  for (const { path } of jsonFiles) {
    const parts = path.split("/");
    // parts[-1] is the filename; everything before is folders
    for (let i = 1; i < parts.length; i++) {
      allFolderPaths.add(parts.slice(0, i).join("/"));
    }
  }

  // Sort by depth so parents are created before children
  const sortedPaths = Array.from(allFolderPaths).sort(
    (a, b) => a.split("/").length - b.split("/").length,
  );

  for (const folderPath of sortedPaths) {
    const parts = folderPath.split("/");
    const name = parts[parts.length - 1];
    const parentPath = parts.slice(0, -1).join("/");
    const parentId = parentPath ? (folderIdMap.get(parentPath) ?? null) : null;

    try {
      const folder = await folderApi.create({ name, parent_id: parentId });
      folderIdMap.set(folderPath, folder.id);
    } catch {
      showToast(`Failed to create folder: ${name}`);
      return;
    }
  }

  // Import workflows
  let imported = 0;
  let credentials: import("@/types/credential").CredentialListItem[] = [];
  try {
    credentials = await credentialsApi.list();
  } catch {
    credentials = [];
  }

  const sanitizeContext: WorkflowImportSanitizeContext = {
    availableWorkflowIds: new Set(workflows.value.map((w) => w.id)),
    ownedCredentialIds: new Set(
      credentials
        .filter((c) => c.is_shared !== true)
        .map((c) => c.id),
    ),
  };

  for (const { path, content } of jsonFiles) {
    try {
      const parsed = JSON.parse(content) as { nodes?: WorkflowNode[]; edges?: WorkflowEdge[]; name?: string };
      if (!parsed.nodes || !Array.isArray(parsed.nodes)) continue;

      const parts = path.split("/");
      const fileName = parts[parts.length - 1].replace(/\.json$/i, "");
      const folderPath = parts.slice(0, -1).join("/");
      const folderId = folderIdMap.get(folderPath) ?? null;

      const workflowName = parsed.name || fileName || "Imported Workflow";
      const sanitizedNodes = parsed.nodes.map((node) => sanitizeImportedNode(node, sanitizeContext));

      const workflow = await workflowApi.create({
        name: workflowName,
        description: `Imported from ${file.name}`,
      });
      await workflowApi.update(workflow.id, {
        nodes: sanitizedNodes,
        edges: parsed.edges || [],
      });

      if (folderId) {
        await folderApi.moveWorkflowToFolder(folderId, workflow.id);
      }

      imported++;
    } catch {
      // Continue with remaining workflows
    }
  }

  const total = jsonFiles.length;
  if (imported === total) {
    showToast(
      imported === 1
        ? `Folder imported successfully (${imported} workflow)`
        : `Folder imported successfully (${imported} workflows)`,
      "success",
    );
  } else {
    showToast(`${imported}/${total} workflows imported`);
  }

  await folderStore.fetchFolderTree();
  await loadWorkflows();
}
```

- [ ] **Step 5: Extend `handleJsonDrop` to route ZIP files**

Find `handleJsonDrop` (around line 808). After `isDraggingJsonFile.value = false;` and before the null check, add a ZIP branch:

```ts
async function handleJsonDrop(event: DragEvent): Promise<void> {
  event.preventDefault();
  isDraggingJsonFile.value = false;

  const files = event.dataTransfer?.files;
  if (!files || files.length === 0) return;

  const file = files[0];

  // ZIP branch
  if (file.type === "application/zip" || file.type === "application/x-zip-compressed" || file.name.endsWith(".zip")) {
    await importZipFile(file);
    return;
  }

  // Existing JSON branch (unchanged below this point)
  const isJson = file.type === "application/json" || file.name.endsWith(".json");
  if (!isJson) {
    showToast("Please drop a JSON or ZIP file");
    return;
  }
  // ... rest of existing JSON handling unchanged
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/DashboardView.vue
git commit -m "feat: import folder structure from ZIP drag & drop"
```

---

## Task 6: Documentation updates

**Files:**
- Modify: `frontend/src/docs/content/reference/download-import.md`
- Modify: `frontend/src/docs/content/reference/workflow-organization.md`

- [ ] **Step 1: Update `download-import.md`**

Replace the entire file content with:

```markdown
# Download & Import

Export workflows or entire folders as files, or import them via drag & drop. Use this for backup, sharing, or migrating workflows between instances.

## Download Workflow (JSON)

**Location:** Editor toolbar → **Download** button (visible on large screens)

**What it exports:**
- `nodes` – All nodes on the canvas
- `edges` – All connections between nodes

**Filename:** `{workflow-name}.json`

**Format:** See [Workflow Structure](./workflow-structure.md) for the JSON schema.

## Download Folder (ZIP)

**Location:** Dashboard → Workflows tab → folder 3-dot menu → **Download as ZIP**

**What it exports:**
- All workflows in the folder and all sub-folders, recursively
- Folder hierarchy preserved as directories inside the ZIP

**ZIP structure:**
```
FolderName/
  workflow1.json
  workflow2.json
  SubFolder/
    workflow3.json
    DeepSub/
      workflow4.json
```

Each `.json` file contains `{ name, nodes, edges }`.

## Import

### From Dashboard (Workflows Tab)

1. Go to the [Workflows](../tabs/workflows-tab.md) tab
2. Drag a **JSON** or **ZIP** file onto the workflow area

**JSON file:** A new workflow is created. The workflow name comes from the `name` field in the JSON, or the filename if `name` is missing.

**ZIP file:** The entire folder structure is recreated at root level. Each `.json` file inside the ZIP becomes a workflow placed in the matching folder. Credentials and cross-workflow references that don't exist in the current instance are cleared automatically. If some workflows fail to import, a summary shows how many succeeded.

### From Canvas (Editor)

1. Open a workflow in the editor
2. Drag a JSON file onto the canvas
3. If the canvas already has nodes or edges, a confirmation dialog asks whether to replace the current workflow

## File Formats

### JSON (single workflow)

```json
{
  "nodes": [...],
  "edges": [...],
  "name": "Optional workflow name"
}
```

- `nodes` – Required; array of node objects
- `edges` – Optional; array of edge objects (defaults to `[]`)
- `name` – Optional; used when creating the workflow on import

### ZIP (folder)

ZIP archive where the directory structure mirrors the folder hierarchy. Each file is a workflow JSON (see above). Folder and workflow names are derived from the directory and file names respectively.

See [Workflow Structure](./workflow-structure.md) for node and edge formats.

## Use Cases

- **Backup** – Download workflows or entire folders before major changes
- **Sharing** – Export and share with teammates
- **Migration** – Move workflows or folder structures between Heym instances
- **Version control** – Store workflow JSON in Git alongside code

## Related

- [Workflow Structure](./workflow-structure.md) – JSON format for nodes and edges
- [Workflows Tab](../tabs/workflows-tab.md) – Create workflows and import via drag & drop
- [Workflow Organization](./workflow-organization.md) – Folders and sub-folders
- [Canvas Features](./canvas-features.md) – Editor features including canvas import
```

- [ ] **Step 2: Update `workflow-organization.md`**

In the **API** table under **Folders and Sub-folders**, add the new row:

```
| `GET /folders/{id}/export` | Download folder + subfolders as ZIP |
```

In the **Context menu** bullet under **Dashboard UI**, update:

```
- **Context menu** – New Subfolder, Rename, Download as ZIP, Delete per folder
```

Add a new bullet under **Drop zones**:

```
- **ZIP drop** – Drop a ZIP file onto the workflow area to import a folder structure at root level
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/docs/content/reference/download-import.md \
        frontend/src/docs/content/reference/workflow-organization.md
git commit -m "docs: update download-import and workflow-organization for ZIP feature"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| Folder context menu → Download as ZIP | Task 4 |
| Backend ZIP endpoint, recursive, directory structure | Tasks 1 + 2 |
| Frontend API `exportZip` client | Task 3 |
| JSZip client-side import | Task 5 |
| ZIP dropped at root level always | Task 5, `_importZipFile`: parentId always null for top-level folder |
| Sanitize credentials on import | Task 5, `sanitizeImportedNode` applied |
| Partial failure handling + summary toast | Task 5 |
| `download-import.md` updated | Task 6 |
| `workflow-organization.md` updated | Task 6 |

**No placeholders found.**

**Type consistency:**
- `folderApi.exportZip(id: string): Promise<Blob>` — defined Task 3, used Task 4 ✓
- `folderApi.create({ name, parent_id })` — existing API, used Task 5 ✓
- `WorkflowImportSanitizeContext` — defined in existing `DashboardView.vue`, used Task 5 ✓
- `sanitizeImportedNode` — existing function in `DashboardView.vue`, used Task 5 ✓
- `_build_zip_bytes(folder_name, workflows, children)` — defined Task 1, used Task 2 ✓
