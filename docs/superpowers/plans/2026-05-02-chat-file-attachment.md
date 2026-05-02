# Chat File Attachment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add single-file attachment to DashboardChatPanel so the AI agent can route file content (text, image, PDF) to the correct workflow input field.

**Architecture:** Frontend reads the file via `FileReader`/`pdfjs-dist` in a new `useFileAttachment` composable and sends it as `attachment` in the existing dashboard-chat API request. Backend embeds text/PDF content in the user message string; images become an OpenAI multipart content array. A routing instruction in the system prompt tells the LLM how to map the file to the correct workflow input field.

**Tech Stack:** Vue 3 + TypeScript (strict), FastAPI + Pydantic, pdfjs-dist (new dependency), existing FileReader API.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/composables/useFileAttachment.ts` | File reading (FileReader + PDF.js), kind detection, size validation |
| Modify | `backend/app/api/ai_assistant.py:93` | Add `FileAttachment` model before `DashboardChatRequest`; add `_ATTACHMENT_ROUTING_INSTRUCTIONS` constant and `_build_user_message` helper after `_get_dashboard_chat_node_label`; extend `DashboardChatRequest` with `attachment`; wire into `dashboard_chat_stream` |
| Modify | `frontend/src/services/api.ts:1149` | Add `FileAttachmentPayload` interface; add `attachment?` to `DashboardChatRequest`; serialize in `dashboardChatStream` body |
| Modify | `frontend/src/components/Dashboard/DashboardChatPanel.vue` | Import composable; extend `ChatMessage` with `attachmentName?`; add state, file handler, UI (hidden input, paperclip button, badge, file chip in bubble), update `handleSubmit` |
| Modify | `backend/tests/test_dashboard_chat_api.py` | Add `BuildUserMessageTests` class (3 unit tests) and 1 integration test for attachment routing prompt |

---

## Task 1: Backend — `FileAttachment` model + `_build_user_message` (TDD)

**Files:**
- Modify: `backend/app/api/ai_assistant.py:93`
- Test: `backend/tests/test_dashboard_chat_api.py`

- [ ] **Step 1: Write failing tests**

Add a new test class at the bottom of `backend/tests/test_dashboard_chat_api.py`:

```python
from app.api.ai_assistant import (
    DashboardChatRequest,
    dashboard_chat_stream,
    stream_dashboard_chat,
    FileAttachment,
    _build_user_message,
)


class BuildUserMessageTests(unittest.TestCase):
    def test_no_attachment_returns_string_content(self) -> None:
        result = _build_user_message("Hello", None)
        self.assertEqual(result, {"role": "user", "content": "Hello"})

    def test_text_attachment_embeds_in_content(self) -> None:
        attachment = FileAttachment(name="notes.txt", kind="text", content="line1\nline2")
        result = _build_user_message("Summarize this", attachment)
        self.assertEqual(result["role"], "user")
        self.assertIsInstance(result["content"], str)
        self.assertIn("Summarize this", result["content"])
        self.assertIn("[ATTACHED FILE: notes.txt]", result["content"])
        self.assertIn("line1\nline2", result["content"])

    def test_pdf_attachment_embeds_in_content(self) -> None:
        attachment = FileAttachment(name="report.pdf", kind="pdf", content="Extracted text")
        result = _build_user_message("Analyze this", attachment)
        self.assertIsInstance(result["content"], str)
        self.assertIn("[ATTACHED FILE: report.pdf]", result["content"])
        self.assertIn("Extracted text", result["content"])

    def test_image_attachment_builds_multipart_content(self) -> None:
        attachment = FileAttachment(
            name="photo.png", kind="image", content="data:image/png;base64,abc123"
        )
        result = _build_user_message("Describe this", attachment)
        self.assertEqual(result["role"], "user")
        content = result["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 2)
        self.assertEqual(content[0], {"type": "text", "text": "Describe this"})
        self.assertEqual(content[1], {"type": "image_url", "url": "data:image/png;base64,abc123"})
```

Also update the import at the top of the test file — change the existing import line from:
```python
from app.api.ai_assistant import DashboardChatRequest, dashboard_chat_stream, stream_dashboard_chat
```
to:
```python
from app.api.ai_assistant import (
    DashboardChatRequest,
    FileAttachment,
    _build_user_message,
    dashboard_chat_stream,
    stream_dashboard_chat,
)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_dashboard_chat_api.py::BuildUserMessageTests -v
```

Expected: `ImportError: cannot import name 'FileAttachment'` (or similar — the names don't exist yet).

- [ ] **Step 3: Add `FileAttachment` and `_build_user_message` to `ai_assistant.py`**

In `backend/app/api/ai_assistant.py`, find the block around line 93 that starts with `class DashboardChatRequest`. Insert the `FileAttachment` class **before** it:

```python
class FileAttachment(BaseModel):
    name: str
    kind: Literal["text", "image", "pdf"]
    content: str  # plain text for text/pdf, base64 data URL for images
```

After `_get_dashboard_chat_node_label` (around line 116), add:

```python
_ATTACHMENT_ROUTING_INSTRUCTIONS = (
    "When the user has attached a file, route its content to the most appropriate "
    "workflow input field when calling a workflow tool:\n"
    "- Image attachment → fields named \"image\", \"base64\", \"photo\", \"picture\", or similar\n"
    "- Text/PDF attachment → fields named \"text\", \"document\", \"content\", \"file\", \"data\", or similar\n"
    "- If no dedicated field exists → embed the content in the primary message/query/input field"
)


def _build_user_message(message: str, attachment: FileAttachment | None) -> dict:
    """Build the user role message dict, embedding attachment content when present."""
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
    embedded = f"{message}\n\n[ATTACHED FILE: {attachment.name}]\n{attachment.content}"
    return {"role": "user", "content": embedded}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_dashboard_chat_api.py::BuildUserMessageTests -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/api/ai_assistant.py backend/tests/test_dashboard_chat_api.py
git commit -m "feat: add FileAttachment model and _build_user_message helper"
```

---

## Task 2: Backend — Wire attachment into `dashboard_chat_stream`

**Files:**
- Modify: `backend/app/api/ai_assistant.py` (lines ~93 and ~2002 and ~2037-2043)
- Test: `backend/tests/test_dashboard_chat_api.py`

- [ ] **Step 1: Write a failing test for routing system prompt injection**

Add to `DashboardChatApiTests` in `backend/tests/test_dashboard_chat_api.py`:

```python
async def test_dashboard_chat_injects_routing_instructions_when_attachment_present(
    self,
) -> None:
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.type = CredentialType.openai
    credential.encrypted_config = "encrypted-config"

    current_user = MagicMock()
    current_user.id = uuid.uuid4()
    current_user.user_rules = None

    http_request = MagicMock()
    http_request.is_disconnected = AsyncMock(return_value=False)

    captured: dict[str, object] = {}

    async def fake_stream(
        _client: object,
        _model: str,
        system_prompt: str,
        messages: list[dict],
        _db: object,
        _user: object,
        _provider: str,
        _public_base_url: str,
        _trace_context: object,
        _cancel_event: object,
    ):
        captured["system_prompt"] = system_prompt
        captured["messages"] = messages
        yield 'data: {"type":"done"}\n\n'

    request = DashboardChatRequest(
        credential_id=credential.id,
        model="gpt-4o-mini",
        message="Analyze this",
        attachment=FileAttachment(name="data.csv", kind="text", content="a,b\n1,2"),
    )

    db = AsyncMock()

    with (
        patch("app.api.ai_assistant.get_credential_for_user", return_value=credential),
        patch("app.api.ai_assistant.decrypt_config", return_value={}),
        patch("app.api.ai_assistant.get_openai_client", return_value=(MagicMock(), "openai")),
        patch("app.api.ai_assistant.get_workflows_for_user_with_inputs", new_callable=AsyncMock, return_value=[]),
        patch("app.api.ai_assistant._load_agents_md_content", return_value=None),
        patch("app.api.ai_assistant.build_public_base_url", return_value="http://localhost"),
        patch("app.api.ai_assistant.stream_dashboard_chat", side_effect=fake_stream),
    ):
        response = await dashboard_chat_stream(
            http_request=http_request,
            request=request,
            current_user=current_user,
            db=db,
        )
        # consume the streaming response
        chunks = [chunk async for chunk in response.body_iterator]

    self.assertIn("route its content", captured["system_prompt"])
    # user message should embed the CSV content
    last_msg = captured["messages"][-1]
    self.assertIsInstance(last_msg["content"], str)
    self.assertIn("[ATTACHED FILE: data.csv]", last_msg["content"])
    self.assertIn("a,b\n1,2", last_msg["content"])
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && uv run pytest tests/test_dashboard_chat_api.py::DashboardChatApiTests::test_dashboard_chat_injects_routing_instructions_when_attachment_present -v
```

Expected: FAIL — `DashboardChatRequest` doesn't accept `attachment` yet.

- [ ] **Step 3: Extend `DashboardChatRequest` with `attachment` field**

In `backend/app/api/ai_assistant.py`, find `DashboardChatRequest` (around line 93, now shifted slightly due to Task 1 additions). Add the `attachment` field:

```python
class DashboardChatRequest(BaseModel):
    credential_id: uuid.UUID
    model: str
    message: str
    conversation_history: list[dict] | None = None
    chat_surface: Literal["dashboard", "documentation"] | None = None
    user_rules: str | None = None
    client_local_datetime: str | None = None
    attachment: FileAttachment | None = None
```

- [ ] **Step 4: Replace direct message append and inject routing prompt in `dashboard_chat_stream`**

In `backend/app/api/ai_assistant.py`, find the `dashboard_chat_stream` function (around line 1976). Locate the line:

```python
messages.append({"role": "user", "content": request.message})
```

Replace it with:

```python
messages.append(_build_user_message(request.message, request.attachment))
```

Then find the block that builds `system_prompt` — after the `client_local_datetime` block (the last `if request.client_local_datetime...` block, around line 2037). Add **after** that block:

```python
    if request.attachment:
        system_prompt = system_prompt + "\n\n" + _ATTACHMENT_ROUTING_INSTRUCTIONS
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_dashboard_chat_api.py -v
```

Expected: all tests PASS (including the new routing test and all pre-existing tests).

- [ ] **Step 6: Run full check**

```bash
cd backend && uv run ruff format . && uv run ruff check . && uv run pytest tests/ -x -q
```

Expected: no lint errors, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/tests/test_dashboard_chat_api.py
git commit -m "feat: wire file attachment into dashboard chat stream"
```

---

## Task 3: Frontend — `useFileAttachment` composable + install pdfjs-dist

**Files:**
- Create: `frontend/src/composables/useFileAttachment.ts`

- [ ] **Step 1: Install pdfjs-dist**

```bash
cd frontend && bun add pdfjs-dist
```

Expected: `pdfjs-dist` added to `frontend/package.json` and `bun.lockb` updated.

- [ ] **Step 2: Create the composable**

Create `frontend/src/composables/useFileAttachment.ts` with this exact content:

```typescript
import { ref } from "vue";

export interface AttachedFile {
  name: string;
  kind: "text" | "image" | "pdf";
  mimeType: string;
  content: string;
  sizeKb: number;
}

const TEXT_EXTENSIONS = new Set([
  "txt", "csv", "json", "md", "py", "ts", "js", "html", "xml", "yaml", "yml", "log",
]);
const IMAGE_MIME_TYPES = new Set([
  "image/jpeg", "image/png", "image/gif", "image/webp",
]);
const MAX_TEXT_BYTES = 500 * 1024;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_PDF_BYTES = 5 * 1024 * 1024;
const MAX_CONTENT_CHARS = 100_000;

function detectKind(file: File): "text" | "image" | "pdf" | null {
  if (file.type === "application/pdf") return "pdf";
  if (IMAGE_MIME_TYPES.has(file.type)) return "image";
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (TEXT_EXTENSIONS.has(ext)) return "text";
  return null;
}

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsText(file);
  });
}

function readFileAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

async function extractPdfText(file: File): Promise<string> {
  const { getDocument, GlobalWorkerOptions } = await import("pdfjs-dist");
  GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url,
  ).href;
  const buffer = await file.arrayBuffer();
  const pdf = await getDocument({ data: buffer }).promise;
  const pages: string[] = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const textContent = await page.getTextContent();
    const pageText = textContent.items
      .map((item: Record<string, unknown>) => (typeof item["str"] === "string" ? item["str"] : ""))
      .join(" ");
    pages.push(pageText);
  }
  const full = pages.join("\n");
  return full.length > MAX_CONTENT_CHARS ? full.slice(0, MAX_CONTENT_CHARS) : full;
}

export function useFileAttachment() {
  const attachedFile = ref<AttachedFile | null>(null);
  const attachmentError = ref<string | null>(null);
  const attachmentLoading = ref(false);

  async function processFile(file: File): Promise<void> {
    attachmentError.value = null;
    const kind = detectKind(file);
    if (!kind) {
      attachmentError.value = "Unsupported file type";
      return;
    }
    const maxBytes = kind === "image" ? MAX_IMAGE_BYTES : kind === "pdf" ? MAX_PDF_BYTES : MAX_TEXT_BYTES;
    if (file.size > maxBytes) {
      const maxMb = maxBytes / (1024 * 1024);
      attachmentError.value = `File too large (max ${maxMb} MB)`;
      return;
    }

    attachmentLoading.value = true;
    try {
      let content: string;
      if (kind === "image") {
        content = await readFileAsDataURL(file);
      } else if (kind === "pdf") {
        content = await extractPdfText(file);
      } else {
        content = await readFileAsText(file);
        if (content.length > MAX_CONTENT_CHARS) {
          content = content.slice(0, MAX_CONTENT_CHARS);
        }
      }
      attachedFile.value = {
        name: file.name,
        kind,
        mimeType: file.type,
        content,
        sizeKb: Math.round(file.size / 1024),
      };
    } catch {
      attachmentError.value =
        kind === "pdf" ? "Could not read PDF" : "Failed to read file";
    } finally {
      attachmentLoading.value = false;
    }
  }

  function clearAttachment(): void {
    attachedFile.value = null;
    attachmentError.value = null;
    attachmentLoading.value = false;
  }

  return { attachedFile, attachmentError, attachmentLoading, processFile, clearAttachment };
}
```

- [ ] **Step 3: Verify TypeScript compiles cleanly**

```bash
cd frontend && bun run typecheck
```

Expected: no errors in `useFileAttachment.ts`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/composables/useFileAttachment.ts frontend/package.json bun.lockb
git commit -m "feat: add useFileAttachment composable with pdfjs-dist support"
```

---

## Task 4: Frontend — Update `api.ts` types and serialization

**Files:**
- Modify: `frontend/src/services/api.ts:1149-1159` (DashboardChatRequest interface)
- Modify: `frontend/src/services/api.ts:1575-1587` (dashboardChatStream body)

- [ ] **Step 1: Add `FileAttachmentPayload` interface and extend `DashboardChatRequest`**

In `frontend/src/services/api.ts`, find the `DashboardChatRequest` interface (around line 1149):

```typescript
export interface DashboardChatRequest {
  credentialId: string;
  model: string;
  message: string;
  conversationHistory?: Array<{ role: string; content: string }>;
  chatSurface?: "dashboard" | "documentation";
  /** User rules / custom instructions from settings; included in dashboard chat if set. */
  userRules?: string | null;
  /** Client local date and time (one line), sent at request time. */
  clientLocalDatetime?: string | null;
}
```

Replace it with:

```typescript
export interface FileAttachmentPayload {
  name: string;
  kind: "text" | "image" | "pdf";
  content: string;
}

export interface DashboardChatRequest {
  credentialId: string;
  model: string;
  message: string;
  conversationHistory?: Array<{ role: string; content: string }>;
  chatSurface?: "dashboard" | "documentation";
  /** User rules / custom instructions from settings; included in dashboard chat if set. */
  userRules?: string | null;
  /** Client local date and time (one line), sent at request time. */
  clientLocalDatetime?: string | null;
  attachment?: FileAttachmentPayload;
}
```

- [ ] **Step 2: Serialize `attachment` in the fetch body**

In `frontend/src/services/api.ts`, find the `dashboardChatStream` function body (around line 1575). The `body: JSON.stringify({...})` block currently ends with `clientLocalDatetime`. Add attachment serialization:

Find:
```typescript
      body: JSON.stringify({
        credential_id: request.credentialId,
        model: request.model,
        message: request.message,
        conversation_history: request.conversationHistory,
        ...(request.chatSurface ? { chat_surface: request.chatSurface } : {}),
        ...(request.userRules?.trim()
          ? { user_rules: request.userRules.trim() }
          : {}),
        ...(request.clientLocalDatetime?.trim()
          ? { client_local_datetime: request.clientLocalDatetime.trim() }
          : {}),
      }),
```

Replace with:
```typescript
      body: JSON.stringify({
        credential_id: request.credentialId,
        model: request.model,
        message: request.message,
        conversation_history: request.conversationHistory,
        ...(request.chatSurface ? { chat_surface: request.chatSurface } : {}),
        ...(request.userRules?.trim()
          ? { user_rules: request.userRules.trim() }
          : {}),
        ...(request.clientLocalDatetime?.trim()
          ? { client_local_datetime: request.clientLocalDatetime.trim() }
          : {}),
        ...(request.attachment
          ? {
              attachment: {
                name: request.attachment.name,
                kind: request.attachment.kind,
                content: request.attachment.content,
              },
            }
          : {}),
      }),
```

- [ ] **Step 3: Verify TypeScript compiles cleanly**

```bash
cd frontend && bun run typecheck
```

Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: add FileAttachmentPayload to DashboardChatRequest api type"
```

---

## Task 5: Frontend — DashboardChatPanel UI + state + submit

**Files:**
- Modify: `frontend/src/components/Dashboard/DashboardChatPanel.vue`

- [ ] **Step 1: Update imports and `ChatMessage` interface**

At the top of `<script setup lang="ts">`, change:

```typescript
import { Bot, Check, ChevronDown, Copy, Loader2, Mic, MicOff, Send, Square, Trash2 } from "lucide-vue-next";
```

to:

```typescript
import { Bot, Check, ChevronDown, Copy, Loader2, Mic, MicOff, Paperclip, Send, Square, Trash2, X } from "lucide-vue-next";
```

Add the composable import after the existing internal imports:

```typescript
import { useFileAttachment } from "@/composables/useFileAttachment";
import type { AttachedFile } from "@/composables/useFileAttachment";
```

Update the `ChatMessage` interface:

```typescript
interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  images?: string[];
  attachmentName?: string;
}
```

- [ ] **Step 2: Add composable state and file input ref**

After the existing `const route = useRoute()` line, add:

```typescript
const { attachedFile, attachmentError, attachmentLoading, processFile, clearAttachment } =
  useFileAttachment();
const fileInputRef = ref<HTMLInputElement | null>(null);

function openFilePicker(): void {
  fileInputRef.value?.click();
}

async function handleFileInputChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  await processFile(file);
  // reset input so the same file can be re-selected after clearing
  input.value = "";
}
```

- [ ] **Step 3: Update `handleSubmit` to include attachment**

Find `handleSubmit` (around line 333). Replace the current function with:

```typescript
function handleSubmit(): void {
  const text = inputText.value.trim();
  if (
    !text
    || streaming.value
    || !selectedCredentialId.value
    || !selectedModel.value
    || modelsLoadFailed.value
    || attachmentError.value !== null
    || attachmentLoading.value
  ) {
    return;
  }

  const userMsg: ChatMessage = {
    id: crypto.randomUUID(),
    role: "user",
    content: text,
    ...(attachedFile.value ? { attachmentName: attachedFile.value.name } : {}),
  };
  messages.value.push(userMsg);
  inputText.value = "";

  const payloadAttachment: AttachedFile | null = attachedFile.value;
  clearAttachment();

  const assistantId = crypto.randomUUID();
  messages.value.push({
    id: assistantId,
    role: "assistant",
    content: "",
  });
  activeAssistantMessageId.value = assistantId;
  streaming.value = true;
  steps.value = [];

  const abortController = new AbortController();
  activeAbortController.value = abortController;

  const templateCtx = buildTemplateContext();
  const baseRules = authStore.user?.user_rules ?? "";
  const combinedRules = [
    baseRules,
    templateCtx ? `\n\n${templateCtx}` : "",
  ]
    .join("")
    .trim();

  aiApi.dashboardChatStream(
    {
      credentialId: selectedCredentialId.value,
      model: selectedModel.value,
      message: text,
      conversationHistory: conversationHistoryForRequest.value,
      userRules: combinedRules || undefined,
      clientLocalDatetime: new Date().toLocaleString(),
      ...(payloadAttachment
        ? {
            attachment: {
              name: payloadAttachment.name,
              kind: payloadAttachment.kind,
              content: payloadAttachment.content,
            },
          }
        : {}),
    },
    (chunk) => {
      const m = messages.value.find((msg) => msg.id === assistantId);
      if (m && m.role === "assistant") {
        m.content += chunk;
        nextTick(scrollToBottomImmediate);
      }
    },
    () => {
      streaming.value = false;
      activeAbortController.value = null;
      activeAssistantMessageId.value = null;
    },
    (err) => {
      streaming.value = false;
      activeAbortController.value = null;
      const m = messages.value.find((msg) => msg.id === assistantId);
      if (m && m.role === "assistant") {
        m.content = m.content || `Error: ${err.message}`;
      }
      activeAssistantMessageId.value = null;
    },
    abortController.signal,
    (label) => {
      steps.value = [...steps.value, label];
    },
    (images) => {
      const m = messages.value.find((msg) => msg.id === assistantId);
      if (m && m.role === "assistant") {
        m.images = [...(m.images ?? []), ...images];
      }
    },
  );
}
```

- [ ] **Step 4: Add hidden file input and paperclip button to template**

In `<template>`, find the `<div class="chat-input-area ...">` wrapper (around line 701). Replace:

```html
    <div class="chat-input-area shrink-0 px-3 sm:px-4 pt-3 sm:pt-4 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <form
        class="flex items-center gap-2 rounded-2xl bg-muted/40 border border-border/40 px-3 py-2 min-h-[52px] focus-within:border-primary/30 focus-within:bg-muted/50 transition-colors"
        @submit.prevent="handleSubmit"
      >
```

with:

```html
    <div class="chat-input-area shrink-0 px-3 sm:px-4 pt-3 sm:pt-4 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <input
        ref="fileInputRef"
        type="file"
        accept=".txt,.csv,.json,.md,.py,.ts,.js,.html,.xml,.yaml,.yml,.log,.jpg,.jpeg,.png,.gif,.webp,.pdf"
        class="hidden"
        @change="handleFileInputChange"
      >
      <!-- Attachment badge -->
      <div
        v-if="attachedFile || attachmentError"
        class="flex items-center gap-2 mb-2 px-1"
      >
        <div
          v-if="attachedFile"
          class="flex items-center gap-1.5 rounded-lg bg-muted/60 border border-border/40 px-2.5 py-1 text-xs text-foreground max-w-xs"
        >
          <Paperclip class="w-3 h-3 shrink-0 text-muted-foreground" />
          <span class="truncate">{{ attachedFile.name }}</span>
          <span class="text-muted-foreground shrink-0">· {{ attachedFile.sizeKb }} KB</span>
          <button
            type="button"
            class="shrink-0 ml-0.5 rounded hover:bg-muted/80 p-0.5"
            aria-label="Remove attachment"
            @click="clearAttachment"
          >
            <X class="w-3 h-3" />
          </button>
        </div>
        <p
          v-if="attachmentError"
          class="text-xs text-destructive"
        >
          {{ attachmentError }}
        </p>
      </div>
      <form
        class="flex items-center gap-2 rounded-2xl bg-muted/40 border border-border/40 px-3 py-2 min-h-[52px] focus-within:border-primary/30 focus-within:bg-muted/50 transition-colors"
        @submit.prevent="handleSubmit"
      >
```

- [ ] **Step 5: Add paperclip button inside the form (before the textarea)**

Inside the `<form>`, just before `<textarea`, add:

```html
        <button
          type="button"
          class="shrink-0 h-9 w-9 min-h-[36px] min-w-[36px] rounded-xl flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/80 disabled:opacity-50 disabled:pointer-events-none touch-manipulation transition-colors"
          :disabled="streaming || attachmentLoading"
          title="Attach file"
          aria-label="Attach file"
          @click="openFilePicker"
        >
          <Loader2
            v-if="attachmentLoading"
            class="w-4 h-4 animate-spin"
          />
          <Paperclip
            v-else
            class="w-4 h-4"
          />
        </button>
```

- [ ] **Step 6: Add attachment chip in user message bubble**

In the message rendering section, find the user message `<p>` tag (around line 684):

```html
            <p
              v-else
              class="whitespace-pre-wrap break-words overflow-wrap-anywhere"
            >
              {{ msg.content }}
            </p>
```

Replace with:

```html
            <template v-else>
              <div
                v-if="msg.attachmentName"
                class="flex items-center gap-1 mb-1.5 text-xs text-primary-foreground/70"
              >
                <Paperclip class="w-3 h-3 shrink-0" />
                <span class="truncate max-w-[200px]">{{ msg.attachmentName }}</span>
              </div>
              <p class="whitespace-pre-wrap break-words overflow-wrap-anywhere">
                {{ msg.content }}
              </p>
            </template>
```

- [ ] **Step 7: Update Send button disabled condition to also block when attachment error is present**

Find the Send button (around line 733):

```html
          :disabled="!inputText.trim() || !selectedCredentialId || !selectedModel || modelsLoadFailed"
```

Replace with:

```html
          :disabled="!inputText.trim() || !selectedCredentialId || !selectedModel || modelsLoadFailed || !!attachmentError || attachmentLoading"
```

- [ ] **Step 8: TypeScript check + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/Dashboard/DashboardChatPanel.vue
git commit -m "feat: add file attachment UI to DashboardChatPanel"
```

---

## Task 6: Verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd /path/to/repo && ./run_tests.sh
```

Expected: all tests pass.

- [ ] **Step 2: Run full check script**

```bash
./check.sh
```

Expected: frontend lint + typecheck pass, backend ruff + tests pass.

- [ ] **Step 3: Manual smoke test**

Start the dev stack:
```bash
./run.sh
```

Open `http://localhost:4017`, navigate to the Chat tab, and verify:
1. Paperclip icon appears in the input bar.
2. Clicking it opens the file picker (filtered to supported types).
3. Select a `.txt` file — badge appears with filename and size.
4. Clicking × removes the badge.
5. Select an image — badge shows correctly.
6. Type a message and send — badge clears, message bubble shows the file chip (filename) above the text.
7. Select a file > 500 KB text file — error message appears, Send is disabled.
8. Select a PDF — loading spinner appears briefly, then badge shows.
9. Unsupported type (e.g. `.exe`) — no badge, no error (file picker filter blocks it).

- [ ] **Step 4: Final commit if any formatting fixes were needed**

```bash
git add -p  # stage any ruff format diffs
git commit -m "chore: apply ruff formatting"
```
