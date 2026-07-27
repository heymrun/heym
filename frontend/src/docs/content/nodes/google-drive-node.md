# Google Drive

The **Google Drive** node lists, downloads, updates, and deletes files and folders in Google Drive via OAuth2. It can also copy a Drive file straight into [Heym Drive](./drive-node.md) with a single operation.

> **This is not the [Drive](./drive-node.md) node.** That node is *Heym Drive* — Heym's own internal file storage. This node talks to Google Drive. The `syncToHeymDrive` operation is the bridge between the two.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | Google Drive (OAuth2) |
| Output | `$nodeLabel.files`, `$nodeLabel.content_base64`, `$nodeLabel.download_url`, `$nodeLabel.status` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | Google Drive credential from [Credentials](../tabs/credentials-tab.md) |
| `gdOperation` | string | Operation: `listFolderFiles`, `downloadFile`, `syncToHeymDrive`, `updateFile`, `removeFile`, `removeFolder` |
| `gdFolderId` | expression | Folder ID or full Drive folder URL. Used by `listFolderFiles` and `removeFolder`. Empty means the Drive root. |
| `gdFileId` | expression | File ID or full Drive/Docs URL. Used by `downloadFile`, `syncToHeymDrive`, `updateFile`, `removeFile`. |
| `gdMaxResults` | expression | For `listFolderFiles`: maximum files to return (default 100). |
| `gdQuery` | expression | For `listFolderFiles`: extra Drive query ANDed with the folder filter, e.g. `mimeType='application/pdf'`. |
| `gdIncludeTrashed` | boolean | For `listFolderFiles`: include trashed files. Default false. |
| `gdExportFormat` | string | For `downloadFile` / `syncToHeymDrive`: `pdf`, `docx`, `xlsx`, `pptx`, `csv`, `txt`. Empty means automatic. Ignored for regular files. |
| `gdFilename` | expression | For `syncToHeymDrive`: override the filename stored in Heym Drive. |
| `gdBase64Content` | expression | For `updateFile`: base64 string or `data:` URL that replaces the file content. |
| `gdNewName` | expression | For `updateFile`: new filename (rename). |
| `gdNewParentId` | expression | For `updateFile`: destination folder ID or URL (move). |
| `gdPermanentDelete` | boolean | For `removeFile` / `removeFolder`: when false (default) the item is trashed and recoverable; when true it is destroyed. |

## File and Folder IDs

`gdFileId`, `gdFolderId`, and `gdNewParentId` accept either the **bare ID** or a **full URL** — Heym extracts the ID automatically. All of these work:

- `https://drive.google.com/file/d/1AbCdEf/view`
- `https://drive.google.com/drive/folders/1FolderXyz`
- `https://docs.google.com/document/d/1DocId/edit`
- `https://drive.google.com/open?id=1AbCdEf`
- `1AbCdEf`

## Google Docs, Sheets, and Slides

Google-native documents have **no downloadable bytes**. They are records on Google's servers, not files — the Drive API returns `403 Only files with binary content can be downloaded` if you ask for their raw content.

`downloadFile` and `syncToHeymDrive` detect these automatically and **export** instead, so no operation fails just because the target is a Google Doc:

| Source | Default export |
|--------|----------------|
| Google Docs | PDF |
| Google Sheets | XLSX |
| Google Slides | PPTX |
| Any other Google-native type | PDF |

Set **Export Format** to override the target. The setting is ignored for regular uploaded files, which always download as-is.

## Operations

| Operation | Required | Description |
|-----------|----------|-------------|
| `listFolderFiles` | — (empty folder = root) | List files in a folder, with an optional query filter |
| `downloadFile` | `gdFileId` | Download file bytes as base64, exporting native docs automatically |
| `syncToHeymDrive` | `gdFileId` | Download from Google Drive and store the result in Heym Drive |
| `updateFile` | `gdFileId` + at least one of content / name / parent | Replace content, rename, and/or move |
| `removeFile` | `gdFileId` | Trash (default) or permanently delete a file |
| `removeFolder` | `gdFolderId` | Trash (default) or permanently delete a folder and its contents |

### Deleting is recoverable by default

`removeFile` and `removeFolder` move the item to **Google Drive trash**, where it can be restored. This is the safe default for something that may run on a schedule or inside a [Loop](./loop-node.md).

Enabling **Delete permanently** destroys the item with no recovery. For `removeFolder`, that also destroys everything inside the folder.

The node also checks the target type: `removeFile` refuses a folder and `removeFolder` refuses a file, so a mistyped ID cannot silently delete the wrong thing.

### updateFile leaves blank fields alone

`updateFile` is an update, not a replace. Fill any combination of content, new name, and new folder — whatever you leave empty is not touched. At least one of the three is required.

## Credential Setup

Google Drive uses an **OAuth2 "Bring Your Own App"** model. You provide your own Google Cloud OAuth2 credentials.

> **This credential grants full Drive access.** Heym requests the `https://www.googleapis.com/auth/drive` scope because the node operates on files you already own. The narrower `drive.file` scope only sees files the app itself created, which would make listing, updating, and deleting your existing files impossible. See [Credential Sharing](../reference/credentials-sharing.md) before sharing this credential with a team.

**Backend configuration:** Set **`FRONTEND_URL`** on the Heym backend to the public URL of the app. The OAuth redirect URI is always `{FRONTEND_URL}/api/credentials/google-drive/oauth/callback` — it is derived only from this setting, not from request headers.

1. Go to [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services** → **Enable APIs** → enable **Google Drive API**.
2. Go to **Credentials** → **Create Credentials** → **OAuth client ID** → select **Web application**.
3. Under **Authorized redirect URIs**, add exactly `{your FRONTEND_URL}/api/credentials/google-drive/oauth/callback`.
4. Copy the **Client ID** and **Client Secret**.
5. In Heym: **Dashboard → Credentials → New → Google Drive (OAuth2)**, paste both values, then click **Connect** and approve access in the popup.

## Output

### listFolderFiles

```json
{
  "status": "success",
  "operation": "listFolderFiles",
  "folder_id": "1FolderXyz",
  "count": 2,
  "files": [
    {
      "id": "1AbC",
      "name": "report.pdf",
      "mime_type": "application/pdf",
      "size_bytes": 20481,
      "modified_time": "2026-07-01T10:00:00.000Z",
      "web_view_link": "https://drive.google.com/file/d/1AbC/view",
      "is_folder": false
    }
  ]
}
```

`size_bytes` is `null` for folders and Google-native files, which do not report a size.

### downloadFile

```json
{
  "status": "success",
  "operation": "downloadFile",
  "id": "1AbC",
  "filename": "Notes.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 20481,
  "exported": true,
  "export_format": "pdf",
  "content_base64": "JVBERi0xLjQ..."
}
```

For a regular file, `exported` is `false` and `export_format` is `null`.

### syncToHeymDrive

```json
{
  "status": "success",
  "operation": "syncToHeymDrive",
  "id": "9f1c2b3d-0000-4000-8000-000000000001",
  "google_file_id": "1AbC",
  "filename": "Notes.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 20481,
  "exported": true,
  "download_url": "https://your-heym-domain/api/files/dl/TOKEN"
}
```

`id` is the new **Heym Drive** file ID, distinct from `google_file_id`.

### updateFile

```json
{
  "status": "success",
  "operation": "updateFile",
  "id": "1AbC",
  "name": "renamed.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 20481,
  "modified_time": "2026-07-27T10:00:00.000Z",
  "updated": ["content", "name"]
}
```

### removeFile / removeFolder

```json
{
  "status": "success",
  "operation": "removeFile",
  "id": "1AbC",
  "name": "report.pdf",
  "deleted": "trashed"
}
```

`deleted` is `"trashed"` or `"permanent"`.

## Example: back up a Drive folder into Heym Drive

1. **[Cron](./cron-node.md)** — run daily.
2. **Google Drive** — `listFolderFiles` on the source folder, with `gdQuery` set to `mimeType='application/pdf'` if you only want PDFs.
3. **[Loop](./loop-node.md)** — iterate `$ListReports.files`.
4. **Google Drive** — `syncToHeymDrive` with `gdFileId` set to `$BackupLoop.item.id` and `gdFilename` set to `$BackupLoop.item.name`.
5. **[Slack](./slack-node.md)** — post a summary of what was backed up.

## Notes

- Every text field accepts `$` expressions, so IDs and filenames can come from earlier nodes.
- Shared drives are supported — the node sets `supportsAllDrives` on every request.
- Downloads are size-checked against the backend's `FILE_MAX_SIZE_MB` setting.
- Attach this node to an [Agent](./agent-node.md) node's tool input and use the bot icon on any field to let the agent fill it at runtime.

## See Also

- [Drive (Heym Drive)](./drive-node.md)
- [Google Sheets](./google-sheets-node.md)
- [Loop](./loop-node.md)
- [Credentials](../reference/credentials.md)
- [Credential Sharing](../reference/credentials-sharing.md)
