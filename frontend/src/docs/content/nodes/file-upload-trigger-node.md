# File Upload Trigger

The **File Upload Trigger** node is a zero-input entry point for workflows that need a **large file** (audio, video, archives) which cannot be embedded as base64 inside a JSON request. Invoking the workflow returns a prefilled, single-use `curl` upload link; uploading a file to that link starts the run with the file attached.

Use it when a caller — including an AI agent like Claude or ChatGPT running in a sandbox — must hand a 20 MB voice recording or a 75 MB video to a Heym workflow.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.file.{id,name,mime,size,download_url}`, `$nodeLabel.uploaded_at` |

## How it works

The node runs in two phases:

1. **Mint.** When the workflow is invoked over HTTP (`POST /api/workflows/{id}/execute`), as an MCP tool, or via the canvas **Run Workflow** button, the run does **not** execute the body. Instead it mints a single-use upload slot and returns:

   ```json
   {
     "file_upload_required": true,
     "curl": "curl -F 'file=@/path/to/your/file' 'https://your-host/api/file-intake/u/<token>'",
     "upload_url": "https://your-host/api/file-intake/u/<token>",
     "expires_at": "2026-06-25T13:00:00+00:00",
     "max_size_mb": 100,
     "allowed_types": ["audio/*"]
   }
   ```

2. **Upload + run.** The caller runs the `curl` with their file. The upload endpoint validates the slot, stores the file, runs the workflow **synchronously**, and returns the workflow output in the upload response. The link is **single-use** — a second upload returns `409`.

On the canvas, **Run Workflow** shows the minted `curl` in the debug panel with a copy button.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ttlMinutes` | number | `60` | How long the upload link stays valid (1–10080 minutes / up to 7 days). |
| `maxSizeMb` | number | `100` | Maximum accepted file size. Hard ceiling is **100 MB**. |
| `allowedTypes` | string | (empty) | Optional comma-separated MIME/extension allowlist, e.g. `audio/*, .wav`. Empty allows any type. |

## Output fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.file.id` | Stored file UUID (a Drive file). |
| `$nodeLabel.file.name` | Original filename. |
| `$nodeLabel.file.mime` | Detected content type. |
| `$nodeLabel.file.size` | Size in bytes. |
| `$nodeLabel.file.download_url` | Authenticated download URL for downstream nodes. |
| `$nodeLabel.uploaded_at` | ISO timestamp of the upload. |

## Example

A transcription workflow:

```
File Upload Trigger ("audio")  →  Transcribe ($audio.file)  →  LLM summary  →  Output
```

1. An agent calls the workflow's MCP tool and receives the `curl`.
2. The agent runs the `curl` with the recording from its sandbox.
3. The upload runs the workflow and the `curl` response contains the transcript summary.

## Security

- The upload URL embeds a high-entropy token — the token **is** the capability, so a sandboxed agent needs no Heym credentials to upload. Only the token's hash is stored server-side.
- Minting requires normal workflow authentication, so only authorized callers can create upload links.
- Every mint and every upload attempt (accepted or rejected — expired, replayed, oversize, disallowed type, unknown token) is written to an append-only audit trail.
- Uploads are enforced single-use, TTL-bounded, and size-capped; oversized uploads are rejected.

## Notes

- The generic HTTP, MCP, and canvas invocation channels remain JSON-only; this node is the supported way to accept multipart file uploads.
- The uploaded file is stored as a normal Drive file, so any downstream node that accepts a file reference (transcribe, send email attachment, etc.) can consume `$nodeLabel.file`.
