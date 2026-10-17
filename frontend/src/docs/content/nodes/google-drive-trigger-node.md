# Google Drive Trigger

The **Google Drive Trigger** node watches a Google Drive folder, or one file, and starts a workflow once for each file that is created, updated, or deleted. It is a zero-input trigger for intake folders, shared contract folders, and report drops.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.event`, `$nodeLabel.file`, `$nodeLabel.changed_fields`, `$nodeLabel.folder_id`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `google_drive` credential |
| `gdtScope` | `folder` \| `file` | Watch the files in a folder (default) or one file |
| `gdtFolderId` | String | Folder ID or URL. Empty watches My Drive. Only files directly inside the folder are watched |
| `gdtFileId` | String | File ID or URL, for file scope |
| `gdtEvents` | Array | Any of `created`, `updated`, `deleted` (default all three). File scope has no `created` |
| `gdtIncludeFolders` | Boolean | Subfolders themselves also start runs (default off) |
| `pollIntervalMinutes` | Integer | How often Heym checks Drive (minimum and default 1) |

These fields take plain values, not `$` expressions.

## Setup Guide

1. Create a **Google Drive (OAuth2)** credential. See [Third-Party Integrations](../reference/integrations.md#google-drive-oauth2).
2. Drag **Google Drive Trigger** onto the canvas and select the credential.
3. Paste the folder URL from your browser, choose the events, and save.

## Trigger Semantics

- The first poll records the folder as it is and starts nothing. Only later changes start runs.
- `created`: a file appears in the folder, including a file moved into it.
- `updated`: the file's name, modification time, size, or type changed.
- `deleted`: the file is no longer in the folder. It was trashed, deleted, or moved out. In file scope, a file you can no longer see counts as deleted.
- Each change starts exactly one run with `trigger_source = "google_drive"`, also when Heym runs several workers or instances. If a run cannot start, the change is tried again on the next poll. A server crash in the moment between recording a change and starting its run can drop that one change; it is never run twice.
- At most 50 runs start per poll; the rest follow on the next polls.
- A folder with more than 5,000 files is skipped with a warning in the logs.
- Changing the credential, folder, file, or the subfolder setting records the folder again without starting runs. Deactivating the node forgets the folder; changes made while it is inactive do not start runs.

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.event` | `created`, `updated`, or `deleted` |
| `$nodeLabel.file.id` | Drive file ID |
| `$nodeLabel.file.name` | File name |
| `$nodeLabel.file.mime_type` | File type |
| `$nodeLabel.file.size_bytes` | Size, `null` for Google Docs, Sheets, Slides and folders |
| `$nodeLabel.file.created_time` | Creation time |
| `$nodeLabel.file.modified_time` | Last modification time |
| `$nodeLabel.file.web_view_link` | Link to open the file |
| `$nodeLabel.file.is_folder` | `true` for subfolders |
| `$nodeLabel.changed_fields` | Fields that changed, on `updated` |
| `$nodeLabel.folder_id` | Watched folder, `root` for My Drive, `null` in file scope |
| `$nodeLabel.triggered_at` | When the change was seen |

For `deleted`, `file` holds the last metadata Heym saw.

## What Heym Stores

Heym keeps the metadata of the watched files (ID, name, type, size, times, link) to tell what changed. It never reads or stores file contents.

## Example Workflow

**New contract in a folder: summarize and post to Slack**

```
googleDriveTrigger → condition → googleDrive (syncToHeymDrive) → converter (pdfToText) → llm → slack
```

- **Condition**: `$contractsFolder.event == "created"`
- **Google Drive**: `gdFileId` is `$contractsFolder.file.id`

## Related

- [Google Drive](./google-drive-node.md): read, update, or remove the file that triggered the run
- [Google Sheets Trigger](./google-sheets-trigger-node.md)
- [Triggers](../reference/triggers.md)
- [Credential Sharing](../reference/credentials-sharing.md)
