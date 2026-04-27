# Skill Builder & AI Builder Filter — Design Spec

**Date:** 2026-04-09  
**Status:** Approved  
**Scope:** Two related features targeting the Agent node's skill authoring and AI Builder context size.

---

## Overview

### Feature 1 — AI Builder Binary Filter

The AI Builder chat assistant (`/api/ai/workflow-assistant`) serializes the entire workflow (all nodes + edges) and sends it to the LLM. When an Agent node has skills containing large Python files or font/image binaries, the serialized payload exceeds the 128k context window and causes errors.

**Fix:** In `DebugPanel.vue`'s `currentWorkflowContext` computed property, filter each agent node's skill files to include only `.md` files (i.e., `SKILL.md`). All `.py` files and binary files are stripped before the workflow is sent to AI Builder.

This is sufficient because:
- SKILL.md already describes the skill's purpose, parameters, and capabilities — all the AI Builder needs to understand the workflow.
- Python implementation details are irrelevant to workflow structure understanding.
- Fonts embedded as Python string constants (e.g., `EMBEDDED_FONT_ZLIB_BASE64`) would not be caught by a base64-encoding check — size-based or extension-based filtering is needed, and SKILL.md-only is the cleanest approach.

**Scope:** Frontend-only. No backend changes.

---

### Feature 2 — Skill Builder Modal

A new AI-powered interface for creating and editing skills directly in the Agent node's properties panel. Two entry points:

1. **"✨ AI Build" button** in the Skills section header → create a new skill from scratch.
2. **"✨" icon** on each skill card → edit an existing skill.

Both open a **modal dialog** (not full-screen, not side drawer) with a chat interface on the left and a file preview panel on the right.

---

## Feature 1: AI Builder Filter

### Change Location

**File:** `frontend/src/components/Panels/DebugPanel.vue`  
**Target:** `currentWorkflowContext` computed property

### Logic

```typescript
const currentWorkflowContext = computed(() => {
  if (workflowStore.nodes.length === 0 && workflowStore.edges.length === 0) {
    return undefined;
  }

  const filteredNodes = workflowStore.nodes.map((node) => {
    if (node.data?.nodeType !== 'agent') return node;
    const filteredSkills = (node.data.skills ?? []).map((skill) => ({
      ...skill,
      files: (skill.files ?? []).filter((f) => f.path.endsWith('.md')),
    }));
    return { ...node, data: { ...node.data, skills: filteredSkills } };
  });

  return {
    id: workflowStore.currentWorkflow?.id,
    name: workflowStore.currentWorkflow?.name,
    nodes: filteredNodes,
    edges: workflowStore.edges,
  };
});
```

### Notes

- Both `assistantStream` call sites in `DebugPanel.vue` (new skill and edit skill) use this same computed — both are fixed automatically.
- Skill names remain visible; only file content is filtered.
- No backend changes required.

---

## Feature 2: Skill Builder Modal

### Architecture

```
PropertiesPanel.vue
  └─ SkillBuilderModal.vue          (new component)
       ├─ Chat panel (left, flex-1)
       └─ File preview panel (right, ~280px)
            └─ Tabs per file (SKILL.md, main.py, ...)

useSkillBuilder.ts                  (new composable)
  └─ manages: stream state, file state, send, reset

skillBuilderApi.ts                  (new service)
  └─ POST /api/ai/skill-builder     (SSE stream)

backend/app/api/skill_builder.py    (new endpoint)
  └─ StreamingResponse (SSE)
```

---

### Backend: `/api/ai/skill-builder`

**Method:** `POST`  
**Auth:** Required (`get_current_user`)  
**Response:** `text/event-stream` (SSE)

#### Request Schema

```python
class SkillBuilderRequest(BaseModel):
    credential_id: str
    model: str
    message: str
    existing_skill: SkillBuilderSkill | None = None   # None = new skill
    conversation_history: list[ConversationMessage] = []

class SkillBuilderSkill(BaseModel):
    name: str
    files: list[SkillFile]          # only .md and .py files, no binaries

class SkillFile(BaseModel):
    path: str
    content: str
    encoding: Literal["text"] = "text"
```

#### SSE Event Types

| Event | Payload | Description |
|-------|---------|-------------|
| `text_chunk` | `{ "content": "..." }` | Streaming chat text |
| `skill_files_update` | `{ "files": [...] }` | AI called `set_skill_files` tool |
| `done` | `{}` | Stream complete |
| `error` | `{ "message": "..." }` | Error occurred |

#### AI Tools

**`set_skill_files`** — AI uses this to output structured file updates:
```json
{
  "name": "set_skill_files",
  "description": "Set the complete skill file contents. Call this whenever you create or update any file.",
  "input_schema": {
    "type": "object",
    "properties": {
      "files": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "path": { "type": "string" },
            "content": { "type": "string" }
          },
          "required": ["path", "content"]
        }
      }
    },
    "required": ["files"]
  }
}
```

When the AI calls `set_skill_files`, the backend emits a `skill_files_update` SSE event and continues streaming.

#### System Prompt Content

The system prompt includes:
- Heym skill DSL reference: SKILL.md format (name, description, parameters, outputs, timeout)
- Available Python libraries: `reportlab` (PDF), `python-docx` (DOCX), `Pillow` (images), `requests`, `pandas`, `openpyxl`, standard library
- Example SKILL.md template
- Example minimal `main.py` with `def execute(params, files) -> dict:` signature
- **Explicit rule:** Do NOT embed fonts or images as Python string constants or base64 in `.py` files. Use reportlab's built-in fonts (Helvetica, Times-Roman, Courier) for PDF. For images, require the user to pass them as input parameters.
- **File structure rule:** Always call `set_skill_files` with the complete current file set (not partial updates).
- Tracing label: `skill_builder`

---

### Frontend: Button Placement (Option C)

**File:** `frontend/src/components/Panels/PropertiesPanel.vue`  
**Location:** Skills section of Agent node (~line 3715–3860)

Changes:
1. Add `✨ AI Build` button next to existing `+ Add Skill` button in the Skills header.
2. Add `✨` icon button to each skill card's header row, alongside the existing remove button.
3. Both buttons open `SkillBuilderModal.vue` — the first with no `existingSkill`, the second with the skill's current `.md` and `.py` files.

---

### Frontend: `SkillBuilderModal.vue`

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│  ✨ Skill Builder    [skill-name or "New Skill"]  [✕]   │
├─────────────────────────────────────┬───────────────────┤
│                                     │  Files            │
│  Chat messages (scrollable)         │  ─────────────    │
│                                     │  📄 SKILL.md  ←tab│
│  [user bubble]                      │  🐍 main.py   ←tab│
│                  [AI bubble]        │                   │
│                                     │  [code viewer,    │
│  [loading indicator during stream]  │   read-only]      │
│                                     │                   │
│  ┌──────────────────────────────┐   │  ─────────────    │
│  │ Skill'i tarif et...    [→]   │   │  [Kaydet & Ekle]  │
│  └──────────────────────────────┘   │                   │
└─────────────────────────────────────┴───────────────────┘
```

**Behavior:**
- Opens with an initial AI greeting explaining what it can do.
- In edit mode: initial message includes the existing skill's SKILL.md content as context.
- When `skill_files_update` SSE event arrives: update the file preview panel tabs in real-time.
- File tabs show read-only code in a `<pre>` element with monospace font (no syntax highlighting library in the project).
- **"Kaydet & Ekle"** button:
  - Disabled until at least one `skill_files_update` has been received.
  - On click: packages current files into a ZIP blob in-browser (using JSZip, already in `frontend/package.json`), then calls the existing skill ZIP ingestion flow (`handleSkillZipDrop` equivalent) to add/update the skill on the agent node.
  - In edit mode: replaces the existing skill in the node's skills array (matched by name from SKILL.md).
  - Closes modal on success.
- ESC key closes modal (no save).
- Modal is `z-50`, backdrop `bg-black/40`.
- Width: `min(90vw, 900px)`, height: `min(85vh, 700px)`.

---

### Frontend: `useSkillBuilder.ts`

State managed by the composable:
- `messages: Ref<ChatMessage[]>` — conversation history
- `currentFiles: Ref<SkillFile[]>` — latest file set from AI
- `isStreaming: Ref<boolean>`
- `error: Ref<string | null>`

Methods:
- `sendMessage(text: string): Promise<void>` — streams via `skillBuilderApi`, appends chunks to last AI message, updates `currentFiles` on `skill_files_update` events
- `reset()` — clear state for new modal open

---

### Frontend: `skillBuilderApi.ts`

Single function mirroring the existing `assistantStream` pattern in `api.ts`:

```typescript
export async function skillBuilderStream(
  request: SkillBuilderRequest,
  onChunk: (text: string) => void,
  onFilesUpdate: (files: SkillFile[]) => void,
  signal: AbortSignal,
): Promise<void>
```

Uses `fetch` with SSE parsing (same pattern as existing AI Builder streaming).

---

## File Checklist

### New Files
- `frontend/src/components/Panels/SkillBuilderModal.vue`
- `frontend/src/composables/useSkillBuilder.ts`
- `frontend/src/services/skillBuilderApi.ts`
- `backend/app/api/skill_builder.py`

### Modified Files
- `frontend/src/components/Panels/DebugPanel.vue` — filter `currentWorkflowContext`
- `frontend/src/components/Panels/PropertiesPanel.vue` — add AI Build / ✨ buttons
- `backend/app/main.py` — import `skill_builder` and add `app.include_router(skill_builder.router, prefix="/api/ai", tags=["Skill Builder"])`

### No Changes Needed
- `backend/app/api/ai_assistant.py` — existing endpoint untouched
- `frontend/src/services/api.ts` — `assistantStream` untouched
- `frontend/src/lib/skillZipParser.ts` — reused as-is for ZIP ingestion

---

## Out of Scope

- Skill versioning or history
- Diff view between old and new skill files
- Multi-turn streaming interruption/cancellation UI (stream completes naturally)
- Backend persistence of skill builder sessions
- Skill sharing or export beyond the existing ZIP mechanism
