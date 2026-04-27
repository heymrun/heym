# Drive Enhancements Design
Date: 2026-04-18

## Overview
Four enhancements to the Drive system: drag-and-drop file upload in the Drive tab, a new `get` operation on the Drive node (with searchable file picker and optional binary download), inline image display in the canvas output panel, and documentation updates via the heym-documentation skill.

---

## 1. Drive Tab — Drag & Drop Upload

### Backend
- New endpoint: `POST /api/files/upload` (multipart/form-data) in `backend/app/api/files.py`
- Accepts a single file upload from authenticated user
- Creates a `GeneratedFile` record: `owner_id` from JWT, `workflow_id=null`, `source_node_label="manual upload"`
- Returns the same `GeneratedFile` response shape as `GET /api/files/{file_id}`

### Frontend
- `DrivePanel.vue`: add `dragover`/`dragleave`/`drop` listeners on the panel root element
- On drag over: show translucent "Drop to upload" overlay (conditional `<div>`, Tailwind classes)
- On drop: call `filesApi.upload(file)`, then refresh the file list
- `api.ts`: add `filesApi.upload(file: File)` method wrapping `POST /api/files/upload`

### Constraints
- No new component — overlay is inline in DrivePanel
- Single file per drop (multiple files dropped: process all sequentially)

---

## 2. Drive Node — `get` Operation

### New Operation
Add `get` to the Drive node operation dropdown alongside existing operations (`delete`, `setPassword`, `setTtl`, `setMaxDownloads`).

### Properties Panel (`PropertiesPanel.vue`)
When `get` is selected:
- **File picker:** Searchable combobox (same pattern as credential selectors) — calls `GET /api/files` on open, displays `filename` as label, stores `id` (UUID) as `driveFileId` value
- **Include binary checkbox:** Boolean field `driveIncludeBinary` (default: false) — label "Include binary content"

### Backend Executor (`workflow_executor.py`)
New `get` operation handler:
1. Fetch `GeneratedFile` by `driveFileId`, validate `owner_id`
2. Always return: `{ id, filename, mime_type, size_bytes, download_url }`
3. If `driveIncludeBinary=true`: read file from `storage_path`, return additional `file_base64` (base64-encoded string)

Output shape:
```json
{
  "id": "<uuid>",
  "filename": "example.png",
  "mime_type": "image/png",
  "size_bytes": 102400,
  "download_url": "https://...",
  "file_base64": "<base64 string, only when driveIncludeBinary=true>"
}
```

### No Schema Changes
File binary is read from `storage_path` on demand — no new DB columns.

### Unit Tests
New test class in `backend/tests/test_drive_node_get.py` (or extend existing drive tests):
- `test_get_returns_metadata` — get without binary; assert output shape, no `file_base64`
- `test_get_with_binary_returns_base64` — get with `driveIncludeBinary=true`; assert `file_base64` is valid base64, content matches file
- `test_get_wrong_owner_raises` — file belongs to different user; assert 404/forbidden
- `test_get_nonexistent_file_raises` — invalid UUID; assert error
- `test_get_binary_missing_file_on_disk` — DB record exists but file missing from disk; assert graceful error

---

## 3. Image Display in Canvas Output Panel

When a Drive node `get` operation result contains:
- `mime_type` starting with `image/`
- `file_base64` present

The canvas output panel renders:
```html
<img src="data:{mime_type};base64,{file_base64}" />
```
instead of the raw base64 string.

Clicking the image opens `ImageLightbox.vue` (already exists, handles data URIs).

Implementation: conditional branch in the existing node output display component — detect Drive node `get` output shape, render image inline.

---

## 4. Documentation

- Update `frontend/src/docs/content/nodes/drive-node.md`:
  - Add `get` operation section: file picker, Include Binary toggle, output fields
  - Expression usage examples: `$driveNode.file_base64`, `$driveNode.download_url`
- Invoke `heym-documentation` skill during implementation for any broader doc site changes

---

## Files Affected

### Backend
- `backend/app/api/files.py` — new upload endpoint
- `backend/app/services/workflow_executor.py` — new `get` operation handler
- `backend/tests/test_drive_node_get.py` — new unit tests

### Frontend
- `frontend/src/components/Drive/DrivePanel.vue` — drag & drop upload
- `frontend/src/services/api.ts` — `filesApi.upload()`
- `frontend/src/components/Panels/PropertiesPanel.vue` — `get` operation UI (file picker + checkbox)
- Canvas output display component — inline image rendering
- `frontend/src/docs/content/nodes/drive-node.md` — documentation
