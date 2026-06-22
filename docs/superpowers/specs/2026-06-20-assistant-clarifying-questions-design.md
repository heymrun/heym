# Assistant Clarifying Questions (Planning Phase) — Design

**Date:** 2026-06-20
**Status:** Approved design, pending implementation plan
**Surfaces:** Workflow canvas assistant (incl. dashboard widget) + chat AI assistant

## Problem

When the AI assistant receives a task with ambiguous parts (missing trigger, goal,
data source, output format, etc.), it currently guesses and immediately emits DSL,
producing workflows the user did not intend. We want the assistant to optionally run
a **planning phase**: ask follow-up questions (buttons + free-text "Other"), collect
the answers, and only then generate the DSL that modifies the workflow.

## Decisions (from brainstorming)

- **Scope:** Both surfaces, via a **shared mechanism** (canvas `workflow-assistant` and
  chat assistant).
- **Flow:** **Multi-round** — the assistant may ask, read answers, and ask again until
  the request is clear enough, then emit DSL.
- **Trigger:** **Model discretion only** — the assistant decides whether to ask. No user
  toggle / "Plan" mode.
- **Mechanism:** **Approach A — fenced JSON block** (`` ```heym-clarify ``), mirroring the
  existing `` ```json `` DSL block. Model-agnostic; no native tool-calling required; one
  shared parser + one shared UI component.

## Architecture & Data Flow

```
User request
    │
    ▼
LLM (workflow-assistant / chat) ── prompt: "if ambiguous, emit heym-clarify block"
    │
    ├─► Unclear → ```heym-clarify {questions:[...]} streamed
    │        │
    │        ▼
    │   Shared parser detects block → <ClarifyCard> rendered (buttons + "Other")
    │        │
    │        ▼
    │   User answers → serialized to plain text → sent back as a new user
    │   message to the SAME endpoint (multi-round: assistant may ask again)
    │        │
    │        └──────────────► (loop until model is confident)
    │
    └─► Clear → existing ```json {nodes,edges} DSL block → applyWorkflowChanges (preview→apply)
```

**No new backend state.** Multi-round runs over the existing `conversation_history`
(canvas) / server-side conversation (chat). No new endpoint. Each Q/A round is a normal
message appended to history.

## Protocol Schema

LLM emits a fenced `heym-clarify` JSON block:

```json
{
  "questions": [
    {
      "id": "trigger",
      "text": "How should this workflow be triggered?",
      "type": "single",          // "single" | "multi" | "text"
      "options": ["Webhook", "Manual", "Scheduled"],
      "allowOther": true          // show an "Other" free-text field
    }
  ]
}
```

- `type: "text"` → free-text only (no `options`).
- `type: "single"` → button/radio, single choice; `allowOther` adds an "Other" input.
- `type: "multi"` → multi-select chips + optional "Other".

**Answer serialization** (user message produced on submit):

```
[Plan answers]
- How should this workflow be triggered? → Webhook
- Which outputs are needed? → Email, Slack, Other: "Telegram channel"
```

Plain text (not JSON) so the LLM reads it directly without re-parsing; model-agnostic.

## Frontend

### New: `frontend/src/components/ui/ClarifyCard.vue` (`<script setup>`, PascalCase, <300 lines)
- Props: `questions: ClarifyQuestion[]`, `disabled: boolean` (locks after submit).
- Emit: `submit(answers: ClarifyAnswer[])`.
- Render: per question — title + `single` (button group) / `multi` (toggle chips) /
  `text` (textarea); `allowOther` adds an "Other" + inline input. Submit button enabled
  once required questions are answered.

### New: `frontend/src/types/clarify.ts`
- `ClarifyQuestion`, `ClarifyAnswer` interfaces.

### New: `frontend/src/utils/parseClarify.ts`
- `extractClarifyBlock(content): ClarifyQuestion[] | null` — mirrors the existing
  `extractWorkflowJson` (`DebugPanel.vue:1461`) `` ```json `` detection (`` ```heym-clarify ``,
  `jsonrepair` fallback parse).
- `serializeAnswers(questions, answers): string` — produces the `[Plan answers]` text.

### Integration — Canvas (`DebugPanel.vue`)
On assistant message completion (`onDone`), in build mode, extract the clarify block; if
present, embed `<ClarifyCard>` under that message and **do not call
`applyWorkflowChanges`** (there is no DSL). Submit → `serializeAnswers` → reuse the
existing `sendAiMessage()` (`DebugPanel.vue:1501`, currently arg-less, reads the input
ref) — add an optional `text?: string` param so answers can be sent programmatically
without touching the input box; falls through the same streaming path with history.

### Integration — Chat (`ChatConversation.vue`)
When rendering an assistant message, check for a clarify block with the same util; if
present, show `<ClarifyCard>`. Submit → `chatStore.sendMessage(conversationId, serialized, …)`.

Both surfaces: card becomes `disabled` after submit (consistent with the existing
tool_calls / preview lock pattern). The raw `` ```heym-clarify `` block is not shown as
markdown — it is replaced by the card.

## Backend (prompt only)

No new endpoint/schema. A shared constant `CLARIFY_PROTOCOL_PROMPT` is defined once and
injected into three system prompts to avoid drift:
- `build_assistant_prompt` (canvas build) — `backend/app/services/workflow_dsl_prompt.py`
- `CANVAS_ASK_SYSTEM_PROMPT` (canvas ask) — optional; ask mode can use the same protocol.
- Chat assistant system prompt — `backend/app/api/ai_assistant.py`.

### HARD CONSTRAINT — do not pollute the synced DSL prompt (heymweb `/convert`)

heymweb's AI Convert (`/convert`) tool syncs the DSL prompt from heymrun via
`heymweb/scripts/sync-dsl-prompt.mjs`, which extracts **only** the triple-quoted
`WORKFLOW_DSL_SYSTEM_PROMPT = """..."""` block (regex
`WORKFLOW_DSL_SYSTEM_PROMPT\s*=\s*"""([\s\S]*?)"""`) into `src/lib/heymDslPrompt.ts`
(`HEYM_DSL_SYSTEM_PROMPT`). That converter is a **one-shot** competitor-workflow → DSL
transform with **no interactive planning phase**.

Therefore:
- `CLARIFY_PROTOCOL_PROMPT` MUST be a **separate top-level constant**, appended at the
  **function level** inside `build_assistant_prompt()` (after `WORKFLOW_DSL_SYSTEM_PROMPT`
  is loaded) and in the chat/ask prompt assembly.
- It MUST NOT appear anywhere inside the `WORKFLOW_DSL_SYSTEM_PROMPT` triple-quoted block,
  nor introduce a second `"""` block whose content the regex could capture.
- Net effect: the synced `HEYM_DSL_SYSTEM_PROMPT` is byte-identical to today; heymweb keeps
  emitting DSL only, never `heym-clarify`. No heymweb change is needed.

Prompt instruction essence:
> If the request is ambiguous (missing trigger, goal, data source, output format, etc.),
> DO NOT emit DSL. Instead emit a single `` ```heym-clarify `` block; ask at most 3–4
> questions; provide `options` where possible and set `allowOther: true` when a genuine
> free answer makes sense. When the user replies with `[Plan answers]`, ask again if still
> ambiguous, otherwise emit the `` ```json `` DSL. For clear requests, emit DSL directly —
> do not ask.

## Error Handling & Edge Cases

- **Malformed/missing block:** parse fails → no card; content flows as normal text (silent
  fallback, same as existing DSL parse behavior).
- **Both clarify and json block in one message:** clarify wins (model is not yet confident);
  DSL ignored + debug log.
- **Empty `questions`:** no card.
- **User types a new message before answering:** card becomes `disabled`; free message flows
  normally (model continues from context).
- **Canvas ask mode:** clarify supported but no DSL afterward (ask mode never applies) — just
  structures the conversation.

## Testing (backend pytest, required)

No frontend UI tests (project rule). Backend:
- `test_clarify_protocol_prompt.py`: assert `CLARIFY_PROTOCOL_PROMPT` is injected into all
  three prompts (`build_assistant_prompt`, canvas ask, chat).
- Assertions that the constant contains the key instructions (`heym-clarify`,
  `[Plan answers]`, "ambiguous → don't emit DSL").
- **Sync-safety regression:** assert `WORKFLOW_DSL_SYSTEM_PROMPT` does NOT contain
  `heym-clarify` / `CLARIFY_PROTOCOL_PROMPT` markers, so heymweb's extracted
  `HEYM_DSL_SYSTEM_PROMPT` stays clean. (Optionally also assert the file has exactly one
  `"""`-delimited `WORKFLOW_DSL_SYSTEM_PROMPT` block.)
- Existing `workflow-assistant` / chat endpoint tests must not regress.

> The parser util (`parseClarify.ts`) is a pure TS function; with no frontend test harness it
> is verified via lint + typecheck + manual testing.

## Out of Scope (YAGNI)

- No user-facing "Plan first" toggle (model discretion only).
- No new persistence / endpoints / DB migration.
- No intermediate plan-summary step between answers and DSL (DSL preview already exists).
- No native tool-call protocol (Approach B rejected).
- No clarifying / planning phase in heymweb's `/convert` (one-shot conversion); the synced
  DSL prompt is deliberately left untouched.
