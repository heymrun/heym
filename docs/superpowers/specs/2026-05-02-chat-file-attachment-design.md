# Chat File Attachment — Design Spec

**Date:** 2026-05-02
**Branch:** impl/chat-docs
**Scope:** DashboardChatPanel only (internal authenticated chat tab)

---

## Overview

Users can attach a single file to a chat message in the DashboardChatPanel. When the agent decides to call a workflow, it intelligently routes the file content to the appropriate workflow input field based on field names. If no dedicated field exists, the content is embedded in the primary message/query field.

---

## User Experience

1. A paperclip icon appears in the chat input bar (left of the Send button).
2. Clicking it opens a native file picker filtered to supported types.
3. After selection, a chip/badge appears above the input: `filename.ext · 42 KB × `.
4. The user types their message and sends. The attachment is cleared after submit.
5. The user message bubble shows an attachment indicator (filename).
6. Only one file at a time. Selecting a new file replaces the previous one.

---

## Supported File Types

| Category | Extensions | Frontend Processing |
|----------|-----------|---------------------|
| Text | `.txt`, `.csv`, `.json`, `.md`, `.py`, `.ts`, `.js`, `.html`, `.xml`, `.yaml`, `.log` | `FileReader.readAsText()` → plain string |
| Image | `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` | `FileReader.readAsDataURL()` → base64 data URL |
| PDF | `.pdf` | `pdfjs-dist` text extraction → plain string |

**Size limits:**
- Text: 500 KB
- Image: 5 MB
- PDF: 5 MB (text extraction result truncated at ~100k chars if needed)

---

## Data Types

### Frontend (`DashboardChatPanel.vue`)

```typescript
interface AttachedFile {
  name: string;
  kind: "text" | "image" | "pdf";
  mimeType: string;
  content: string;   // plain text for text/pdf, base64 data URL for images
  sizeKb: number;
}
```

New reactive state:
```typescript
const attachedFile = ref<AttachedFile | null>(null);
```

### API Request (`api.ts` → `DashboardChatRequest`)

```typescript
interface FileAttachmentPayload {
  name: string;
  kind: "text" | "image" | "pdf";
  content: string;
}

interface DashboardChatRequest {
  // existing fields...
  attachment?: FileAttachmentPayload;
}
```

### Backend (`ai_assistant.py`)

```python
class FileAttachment(BaseModel):
    name: str
    kind: Literal["text", "image", "pdf"]
    content: str  # plain text or base64 data URL

class DashboardChatRequest(BaseModel):
    credential_id: uuid.UUID
    model: str
    message: str
    conversation_history: list[dict] | None = None
    chat_surface: Literal["dashboard", "documentation"] | None = None
    user_rules: str | None = None
    client_local_datetime: str | None = None
    attachment: FileAttachment | None = None  # NEW
```

---

## Backend: LLM Message Construction

In `dashboard_chat_stream`, the user message is currently built as:
```python
messages.append({"role": "user", "content": request.message})
```

With attachment support:

```python
def _build_user_message(message: str, attachment: FileAttachment | None) -> dict:
    if attachment is None:
        return {"role": "user", "content": message}

    if attachment.kind == "image":
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": message},
                {"type": "image_url", "url": attachment.content},
            ],
        }
    else:
        # text or pdf — embed content as labelled block
        embedded = (
            f"{message}\n\n"
            f"[ATTACHED FILE: {attachment.name}]\n"
            f"{attachment.content}"
        )
        return {"role": "user", "content": embedded}
```

---

## Backend: System Prompt Addition

A routing instruction is appended to the system prompt when an attachment is present:

```
When the user has attached a file, route its content to the most appropriate workflow input field when calling a workflow tool:
- Image attachment → fields named "image", "base64", "photo", "picture", or similar
- Text/PDF attachment → fields named "text", "document", "content", "file", "data", or similar
- If no dedicated field exists → embed the content in the primary message/query/input field
```

This leverages the agent's existing knowledge of workflow input field names (already included in the system prompt via `_format_workflows_for_prompt`).

---

## Frontend: Component Changes (`DashboardChatPanel.vue`)

### New state
```typescript
const attachedFile = ref<AttachedFile | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
```

### File reading logic
```typescript
async function handleFileSelected(file: File): Promise<void> {
  // validate size, read with FileReader or pdfjs-dist
  // set attachedFile.value
}
```

### PDF extraction
Uses `pdfjs-dist` (already available or added as dependency). Extracts text page by page, joins with newlines, truncates at 100k characters.

### Submit change
`handleSubmit` passes `attachedFile.value` in the API call:
```typescript
attachment: attachedFile.value
  ? { name: attachedFile.value.name, kind: attachedFile.value.kind, content: attachedFile.value.content }
  : undefined,
```
After submit, `attachedFile.value = null`.

### User message bubble
`ChatMessage` gets an optional `attachmentName?: string` field. On submit, it is set to `attachedFile.value.name`. The bubble renders a small file chip above the message text using this field — the raw `[ATTACHED FILE: ...]` block is never shown to the user.

---

## Error Handling

| Scenario | Handling |
|----------|---------|
| File too large | Show inline error near badge, block submit |
| Unsupported file type | Ignore (file picker filter prevents most cases; fallback alert) |
| PDF.js extraction failure | Show inline error near badge ("Could not read PDF"), block submit |
| Image on non-vision model | LLM will receive multipart content; if model rejects it, backend catches the API error and returns it as a stream error event |

---

## What Is Not In Scope

- Multiple files per message
- File attachment in ChatPortalView (separate feature)
- Server-side file storage for attachments
- Reactive (agent-asks-for-file) flow
- Conversation history re-sending of attachments (current history strips them)

---

## Testing

Backend tests to add:
- `test_dashboard_chat_with_text_attachment`: verifies text content is embedded in user message
- `test_dashboard_chat_with_image_attachment`: verifies multipart content array is built correctly
- `test_build_user_message_no_attachment`: existing behaviour unchanged

No frontend tests yet (per project convention).
