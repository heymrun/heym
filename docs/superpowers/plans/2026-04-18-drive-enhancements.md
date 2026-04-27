# Drive Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add drag-and-drop upload to the Drive tab, a `get` operation to the Drive node (with file picker and optional binary download), inline image display in the debug panel for Drive `get` results, and documentation updates.

**Architecture:** Backend gains a `POST /api/files/upload` endpoint and a `get` branch in the Drive node executor. Frontend extends `filesApi`, `DrivePanel.vue` (drag-drop), `PropertiesPanel.vue` (new operation UI), and `DebugPanel.vue` (image rendering). No DB schema changes — binary is read from disk on demand.

**Tech Stack:** FastAPI, SQLAlchemy async, Python `base64`, Vue 3 + TypeScript strict, Tailwind CSS, existing `ImageLightbox.vue`, existing `Select.vue` and `ExpressionInput.vue` patterns.

---

## File Map

| File | Change |
|------|--------|
| `backend/app/api/files.py` | Add `POST /upload` endpoint |
| `backend/app/services/workflow_executor.py` | Add `get` operation branch in Drive node handler (~line 7800) |
| `backend/tests/test_drive_node.py` | Extend with `DriveNodeGetTests` class |
| `frontend/src/services/api.ts` | Add `filesApi.upload()` method |
| `frontend/src/components/Drive/DrivePanel.vue` | Add drag-and-drop upload |
| `frontend/src/components/Panels/PropertiesPanel.vue` | Add `get` to operations + file picker + checkbox + output ref |
| `frontend/src/components/Panels/DebugPanel.vue` | Extend `getOutputImageSrcs` for Drive `get` |
| `frontend/src/docs/content/nodes/drive-node.md` | Document `get` operation |

---

## Task 1: Backend — Drive `get` executor + unit tests

**Files:**
- Modify: `backend/app/services/workflow_executor.py` (~line 7800, inside `elif node_type == "drive":`)
- Modify: `backend/tests/test_drive_node.py` (add `DriveNodeGetTests` class at the end)

### Step 1.1: Write failing tests

Add this class at the end of `backend/tests/test_drive_node.py` (before `if __name__ == "__main__"`):

```python
class DriveNodeGetTests(unittest.TestCase):
    """Drive node get operation."""

    def test_get_returns_metadata_only(self) -> None:
        """get without driveIncludeBinary returns id/filename/mime_type/size_bytes/download_url, no file_base64."""
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="photo.png",
            mime_type="image/png",
            size_bytes=12345,
            storage_path=f"{owner_id}/{file_id}/photo.png",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(),
            file_id=file_id,
            token="tok123",
            basic_auth_password_hash=None,
        )
        db = _make_db_mock(file_row, default_token=default_token)

        nr = _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": str(file_id),
            },
            owner_id,
            db,
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["operation"], "get")
        self.assertEqual(nr["output"]["id"], str(file_id))
        self.assertEqual(nr["output"]["filename"], "photo.png")
        self.assertEqual(nr["output"]["mime_type"], "image/png")
        self.assertEqual(nr["output"]["size_bytes"], 12345)
        self.assertIn("download_url", nr["output"])
        self.assertNotIn("file_base64", nr["output"])

    def test_get_with_binary_returns_base64(self) -> None:
        """get with driveIncludeBinary=True returns file_base64 as valid base64."""
        import base64

        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_content = b"fake-image-bytes"
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="img.png",
            mime_type="image/png",
            size_bytes=len(file_content),
            storage_path=f"{owner_id}/{file_id}/img.png",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(),
            file_id=file_id,
            token="tok456",
            basic_auth_password_hash=None,
        )
        db = _make_db_mock(file_row, default_token=default_token)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": str(file_id),
                "driveIncludeBinary": True,
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch(
                "app.services.file_storage.build_download_url",
                return_value="/api/files/dl/tok456",
            ),
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_bytes.return_value = file_content
            mock_root.return_value.__truediv__ = MagicMock(return_value=mock_path)

            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "success")
        self.assertIn("file_base64", nr["output"])
        decoded = base64.b64decode(nr["output"]["file_base64"])
        self.assertEqual(decoded, file_content)

    def test_get_wrong_owner_raises(self) -> None:
        """get for file owned by another user results in error."""
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        # DB returns None because owner filter excludes it
        db = _make_db_mock(None)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": str(file_id),
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        self.assertEqual(drive_nr["status"], "error")
        self.assertIn("not found", drive_nr["error"].lower())

    def test_get_nonexistent_file_raises(self) -> None:
        """get with invalid UUID results in error."""
        owner_id = uuid.uuid4()
        db = _make_db_mock(None)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": "not-a-uuid",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        self.assertEqual(drive_nr["status"], "error")

    def test_get_binary_missing_file_on_disk_raises(self) -> None:
        """get with binary when file is missing from disk results in error."""
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="gone.png",
            mime_type="image/png",
            size_bytes=0,
            storage_path=f"{owner_id}/{file_id}/gone.png",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(), file_id=file_id, token="tok789", basic_auth_password_hash=None
        )
        db = _make_db_mock(file_row, default_token=default_token)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": str(file_id),
                "driveIncludeBinary": True,
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = False  # file missing from disk
            mock_root.return_value.__truediv__ = MagicMock(return_value=mock_path)

            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        self.assertEqual(drive_nr["status"], "error")
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend
uv run pytest tests/test_drive_node.py::DriveNodeGetTests -v
```

Expected: All 5 tests FAIL with errors related to unknown `get` operation.

- [ ] **Step 1.3: Implement the `get` operation in workflow_executor.py**

In `backend/app/services/workflow_executor.py`, find the `else:` clause at the end of the Drive node branch (currently at the line that says `raise ValueError(f"Drive Node: unknown operation '{operation}'")`). Replace just that `else` clause with:

```python
                    elif operation == "get":
                        import base64 as _base64

                        default_token = (
                            db.query(FileAccessToken)
                            .filter(
                                FileAccessToken.file_id == file_uuid,
                                FileAccessToken.basic_auth_password_hash.is_(None),
                            )
                            .first()
                        )
                        base_url = getattr(self, "_base_url", "")
                        dl_url = (
                            build_download_url(base_url, default_token.token)
                            if default_token
                            else ""
                        )

                        output = {
                            "status": "success",
                            "operation": "get",
                            "id": str(file_row.id),
                            "filename": file_row.filename,
                            "mime_type": file_row.mime_type,
                            "size_bytes": file_row.size_bytes,
                            "download_url": dl_url,
                        }

                        if node_data.get("driveIncludeBinary"):
                            disk_path = _storage_root() / file_row.storage_path
                            if not disk_path.exists():
                                raise ValueError(
                                    f"Drive Node: file not found on disk: {file_row.filename}"
                                )
                            file_bytes = disk_path.read_bytes()
                            output["file_base64"] = _base64.b64encode(file_bytes).decode()

                    else:
                        raise ValueError(f"Drive Node: unknown operation '{operation}'")
```

The new `elif operation == "get":` block goes between the `elif operation in ("setPassword", "setTtl", "setMaxDownloads"):` block and the existing `else:` clause.

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend
uv run pytest tests/test_drive_node.py::DriveNodeGetTests -v
```

Expected: All 5 tests PASS.

- [ ] **Step 1.5: Run full drive test suite to check no regressions**

```bash
uv run pytest tests/test_drive_node.py -v
```

Expected: All tests PASS.

- [ ] **Step 1.6: Run ruff format and check**

```bash
uv run ruff format backend/app/services/workflow_executor.py backend/tests/test_drive_node.py
uv run ruff check backend/app/services/workflow_executor.py backend/tests/test_drive_node.py
```

Expected: No errors.

- [ ] **Step 1.7: Commit**

```bash
git add backend/app/services/workflow_executor.py backend/tests/test_drive_node.py
git commit -m "feat: add Drive node get operation with optional binary download"
```

---

## Task 2: Backend — Upload endpoint

**Files:**
- Modify: `backend/app/api/files.py`

- [ ] **Step 2.1: Add the upload endpoint**

In `backend/app/api/files.py`, add this import at the top (alongside existing FastAPI imports):

```python
from fastapi import File, UploadFile
```

Then add this endpoint after the `delete_all_files_endpoint` route (around line 168):

```python
@router.post("/upload", response_model=GeneratedFileResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneratedFileResponse:
    """Upload a file manually to Drive."""
    from app.services.file_storage import store_file

    base_url = build_public_base_url(request)
    file_bytes = await file.read()
    row = await store_file(
        db,
        owner_id=user.id,
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        mime_type=file.content_type,
        source_node_label="manual upload",
    )
    token = await create_access_token(db, file_id=row.id, created_by_id=user.id)
    await db.commit()
    await db.refresh(row, ["access_tokens"])
    return _file_to_response(row, base_url)
```

Note: `store_file` is already imported at the top of this file indirectly via `file_storage`. Add the import explicitly:

At the top imports block, add `store_file` to the `file_storage` import:

```python
from app.services.file_storage import (
    build_download_url,
    create_access_token,
    delete_file,
    get_file_path,
    increment_download_count,
    store_file,
    validate_access_token,
    validate_basic_auth,
)
```

- [ ] **Step 2.2: Run ruff format and check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend
uv run ruff format app/api/files.py
uv run ruff check app/api/files.py
```

Expected: No errors.

- [ ] **Step 2.3: Commit**

```bash
git add backend/app/api/files.py
git commit -m "feat: add POST /api/files/upload endpoint for manual Drive uploads"
```

---

## Task 3: Frontend — `filesApi.upload()` API client method

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 3.1: Add upload method to filesApi**

In `frontend/src/services/api.ts`, find the `filesApi` object (around line 2035). Add the `upload` method after `clearAll`:

```typescript
  upload: async (file: File): Promise<GeneratedFile> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post<GeneratedFile>("/files/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },
```

- [ ] **Step 3.2: Typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
bun run typecheck
```

Expected: No errors.

- [ ] **Step 3.3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: add filesApi.upload() for Drive manual upload"
```

---

## Task 4: Frontend — DrivePanel drag & drop upload

**Files:**
- Modify: `frontend/src/components/Drive/DrivePanel.vue`

- [ ] **Step 4.1: Add drag state and upload logic to the `<script setup>` section**

In `DrivePanel.vue`, add to the imports:

```typescript
import { Upload } from "lucide-vue-next";
```

Add these refs and functions after the existing `openShare` function:

```typescript
const isDragging = ref(false);
const uploading = ref(false);
const uploadError = ref("");

function handleDragOver(e: DragEvent): void {
  e.preventDefault();
  isDragging.value = true;
}

function handleDragLeave(e: DragEvent): void {
  // Only clear if leaving the panel entirely (relatedTarget outside)
  if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) {
    isDragging.value = false;
  }
}

async function handleDrop(e: DragEvent): Promise<void> {
  e.preventDefault();
  isDragging.value = false;
  const droppedFiles = Array.from(e.dataTransfer?.files ?? []);
  if (!droppedFiles.length) return;
  uploading.value = true;
  uploadError.value = "";
  try {
    for (const f of droppedFiles) {
      await filesApi.upload(f);
    }
    await loadFiles();
  } catch {
    uploadError.value = "Upload failed";
  } finally {
    uploading.value = false;
  }
}
```

- [ ] **Step 4.2: Update the template root `<div>` to add drag listeners and overlay**

The template's root element is `<div class="space-y-4">`. Change it to:

```html
<div
  class="space-y-4 relative"
  @dragover="handleDragOver"
  @dragleave="handleDragLeave"
  @drop="handleDrop"
>
  <!-- Drag overlay -->
  <div
    v-if="isDragging"
    class="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/10 pointer-events-none"
  >
    <Upload class="w-8 h-8 text-primary mb-2" />
    <p class="text-sm font-medium text-primary">Drop to upload</p>
  </div>

  <!-- Upload progress indicator -->
  <div
    v-if="uploading"
    class="text-sm text-muted-foreground bg-muted/50 p-2 rounded-lg flex items-center gap-2"
  >
    <RefreshCw class="w-3.5 h-3.5 animate-spin" />
    Uploading...
  </div>

  <!-- Upload error -->
  <div
    v-if="uploadError"
    class="text-sm text-destructive bg-destructive/10 p-3 rounded-lg"
  >
    {{ uploadError }}
  </div>

  <!-- … rest of existing template content unchanged … -->
</div>
```

Keep all existing content (header, error, loading, file list, pagination, FileShareDialog) inside this root div.

- [ ] **Step 4.3: Typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
bun run typecheck
```

Expected: No errors.

- [ ] **Step 4.4: Commit**

```bash
git add frontend/src/components/Drive/DrivePanel.vue
git commit -m "feat: add drag-and-drop file upload to DrivePanel"
```

---

## Task 5: Frontend — PropertiesPanel Drive `get` operation UI

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`

- [ ] **Step 5.1: Add `filesApi` to the imports**

Find the line in PropertiesPanel.vue:

```typescript
import { configApi, credentialsApi, dataTablesApi, gristApi, mcpApi, workflowApi } from "@/services/api";
```

Change it to:

```typescript
import { configApi, credentialsApi, dataTablesApi, filesApi, gristApi, mcpApi, workflowApi } from "@/services/api";
```

Also add the `GeneratedFile` type import. Find the file type import block (already has `import type { DataTableListItem }`) and add:

```typescript
import type { GeneratedFile } from "@/types/file";
```

- [ ] **Step 5.2: Add driveFiles state and computed options**

After the existing `const dataTables = ref<DataTableListItem[]>([]);` line, add:

```typescript
const driveFiles = ref<GeneratedFile[]>([]);

const driveFileOptions = computed(() => {
  const options: { value: string; label: string }[] = [
    { value: "", label: "Select file..." },
  ];
  for (const f of driveFiles.value) {
    options.push({ value: f.id, label: f.filename });
  }
  return options;
});
```

- [ ] **Step 5.3: Load drive files when a drive node is selected**

Find the existing watch on `workflowStore.selectedNode?.type` (around line 495). Inside that watch's async handler, add a `drive` case alongside the existing type checks:

```typescript
    if (type === "drive") {
      try {
        const res = await filesApi.list({ limit: 200 });
        driveFiles.value = res.files;
      } catch {
        driveFiles.value = [];
      }
    }
```

- [ ] **Step 5.4: Add `get` to driveOperationOptions**

Find the existing `driveOperationOptions` array (around line 2701):

```typescript
const driveOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "delete", label: "Delete File" },
  { value: "setPassword", label: "Set Password" },
  { value: "setTtl", label: "Set TTL (Expiry)" },
  { value: "setMaxDownloads", label: "Set Max Downloads" },
];
```

Add `get` as the first non-empty option:

```typescript
const driveOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "get", label: "Get File" },
  { value: "delete", label: "Delete File" },
  { value: "setPassword", label: "Set Password" },
  { value: "setTtl", label: "Set TTL (Expiry)" },
  { value: "setMaxDownloads", label: "Set Max Downloads" },
];
```

- [ ] **Step 5.5: Update the Drive node File ID section to show a file picker for `get`**

Find this block in the template (around line 8500):

```html
            <div class="space-y-2">
              <Label>File ID</Label>
              <ExpressionInput
                ref="driveFileIdExpressionInputRef"
                ...
              />
              <p class="text-xs text-muted-foreground">
                ID of the Drive file to manage (from <code>$skill._generated_files[0].id</code>)
              </p>
            </div>
```

Replace it with:

```html
            <div class="space-y-2">
              <Label>File</Label>
              <template v-if="selectedNode.data.driveOperation === 'get'">
                <Select
                  :model-value="selectedNode.data.driveFileId || ''"
                  :options="driveFileOptions"
                  @update:model-value="updateNodeData('driveFileId', $event || undefined)"
                />
                <p class="text-xs text-muted-foreground">
                  Select a file from Drive
                </p>
              </template>
              <template v-else>
                <ExpressionInput
                  ref="driveFileIdExpressionInputRef"
                  :model-value="selectedNode.data.driveFileId || ''"
                  placeholder="$skill._generated_files[0].id"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  :dialog-key-label="
                    selectedNode.data.driveOperation === 'setPassword'
                      ? 'Drive set password · File ID'
                      : 'File ID'
                  "
                  :navigation-enabled="selectedNode.data.driveOperation === 'setPassword'"
                  :navigation-index="0"
                  :navigation-total="driveExpressionFieldCount"
                  @navigate="handleDriveExpressionFieldNavigate"
                  @register-field-index="onDriveRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('driveFileId', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  ID of the Drive file to manage (from <code>$skill._generated_files[0].id</code>)
                </p>
              </template>
            </div>
```

- [ ] **Step 5.6: Add Include Binary checkbox after the File section (get operation only)**

After the File section div, add:

```html
            <div
              v-if="selectedNode.data.driveOperation === 'get'"
              class="space-y-2"
            >
              <Label>Options</Label>
              <div class="flex items-center gap-2">
                <input
                  id="drive-include-binary"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.driveIncludeBinary"
                  @change="updateNodeData('driveIncludeBinary', ($event.target as HTMLInputElement).checked)"
                >
                <Label for="drive-include-binary" class="font-normal text-sm">
                  Include binary content
                </Label>
              </div>
              <p class="text-xs text-muted-foreground">
                When enabled, the file content is returned as base64 in <code>file_base64</code>
              </p>
            </div>
```

- [ ] **Step 5.7: Add output reference section for `get` operation**

Find the output reference `<template v-else>` block in the Drive section:

```html
                <template v-else>
                  <div>Select an operation to see output fields</div>
                </template>
```

Add a `get` case before the existing `v-else-if`:

```html
                <template v-if="selectedNode.data.driveOperation === 'get'">
                  <div>${{ selectedNode.data.label }}.id - file UUID</div>
                  <div>${{ selectedNode.data.label }}.filename - file name</div>
                  <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
                  <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
                  <div>${{ selectedNode.data.label }}.download_url - public download URL</div>
                  <div>${{ selectedNode.data.label }}.file_base64 - base64 content (if enabled)</div>
                </template>
```

The existing `<template v-if="selectedNode.data.driveOperation === 'delete'">` becomes an `v-else-if`.

- [ ] **Step 5.8: Typecheck and lint**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
bun run typecheck
bun run lint
```

Expected: No errors.

- [ ] **Step 5.9: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat: add Drive node get operation UI with file picker and include binary option"
```

---

## Task 6: Frontend — DebugPanel inline image display for Drive `get`

**Files:**
- Modify: `frontend/src/components/Panels/DebugPanel.vue`

- [ ] **Step 6.1: Extend `getOutputImageSrcs` to handle Drive `get` output**

Find `getOutputImageSrcs` in `DebugPanel.vue` (around line 646):

```typescript
function getOutputImageSrcs(output: unknown): string[] {
  const out = output as Record<string, unknown> | undefined;
  if (!out) return [];
  const srcs: string[] = [];
  const img = out.image;
  if (typeof img === "string" && (img.startsWith("data:image/") || img.startsWith("http"))) {
    srcs.push(img);
  }
  const shot = out.screenshot;
  ...
```

Add this block after the `img` check, before the `screenshot` check:

```typescript
  // Drive node get with file_base64 + image mime_type
  const base64 = out.file_base64;
  const mimeType = out.mime_type;
  if (
    typeof base64 === "string" &&
    base64.length > 0 &&
    typeof mimeType === "string" &&
    mimeType.startsWith("image/")
  ) {
    const dataUrl = `data:${mimeType};base64,${base64}`;
    if (!srcs.includes(dataUrl)) srcs.push(dataUrl);
  }
```

- [ ] **Step 6.2: Typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
bun run typecheck
```

Expected: No errors.

- [ ] **Step 6.3: Commit**

```bash
git add frontend/src/components/Panels/DebugPanel.vue
git commit -m "feat: display Drive get images inline in debug panel"
```

---

## Task 7: Documentation

**Files:**
- Modify: `frontend/src/docs/content/nodes/drive-node.md`

- [ ] **Step 7.1: Invoke the heym-documentation skill**

Before editing the doc file, invoke the `heym-documentation` skill to check if additional doc site pages need updating.

- [ ] **Step 7.2: Update drive-node.md**

Update the Parameters table to add the two new parameters:

```markdown
| `driveIncludeBinary` | boolean | Include file content as base64 in output (get only) |
```

Update the Operations table to add `get`:

```markdown
| `get` | driveFileId | Retrieve file metadata (and optionally binary content) from Drive |
```

Add a new `get` output section after the existing Output Access section:

```markdown
**get:**
- `$nodeLabel.id` — UUID of the file
- `$nodeLabel.filename` — file name
- `$nodeLabel.mime_type` — MIME type (e.g. `image/png`)
- `$nodeLabel.size_bytes` — file size in bytes
- `$nodeLabel.download_url` — public download URL
- `$nodeLabel.file_base64` — base64-encoded file content (only when Include Binary is enabled)
```

Add a new example:

```markdown
## Example — Get File and Use Binary in Vision LLM

```json
{
  "type": "drive",
  "data": {
    "label": "fetchImage",
    "driveOperation": "get",
    "driveFileId": "550e8400-e29b-41d4-a716-446655440000",
    "driveIncludeBinary": true
  }
}
```

Reference the binary downstream: `$fetchImage.file_base64`
```

- [ ] **Step 7.3: Run full check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
./check.sh
```

Expected: All lint, typecheck, and backend tests pass.

- [ ] **Step 7.4: Commit**

```bash
git add frontend/src/docs/content/nodes/drive-node.md
git commit -m "docs: document Drive node get operation"
```

---

## Self-Review

**Spec coverage:**
- ✅ Drag & drop upload in Drive tab (Task 4 + Task 2 + Task 3)
- ✅ Drive node `get` with file picker (Task 5)
- ✅ Drive node `get` with Include Binary checkbox (Task 5)
- ✅ getBinary output as base64 in `file_base64` (Task 1)
- ✅ Image display in canvas output panel for Drive `get` (Task 6)
- ✅ Documentation + heym-documentation skill (Task 7)
- ✅ Unit tests for all 5 `get` cases (Task 1)

**Placeholder scan:** No TBD, TODO, or incomplete sections.

**Type consistency:**
- `driveFileId` — used consistently in executor (Task 1), PropertiesPanel (Task 5), existing code
- `driveIncludeBinary` — `node_data.get("driveIncludeBinary")` in executor (Task 1), `selectedNode.data.driveIncludeBinary` in PropertiesPanel (Task 5)
- `file_base64` — output key in executor (Task 1), checked in `getOutputImageSrcs` (Task 6), documented (Task 7)
- `filesApi.upload(file: File)` — defined in Task 3, called in DrivePanel Task 4
