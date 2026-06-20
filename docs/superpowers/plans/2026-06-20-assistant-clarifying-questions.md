# Assistant Clarifying Questions (Planning Phase) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the AI assistant (canvas builder + chat) optionally run a planning phase — emit a `heym-clarify` block of follow-up questions (buttons + free-text "Other"), collect answers, and only then generate the workflow DSL.

**Architecture:** Model-driven, multi-round. The LLM emits a fenced `` ```heym-clarify `` JSON block when a request is ambiguous instead of DSL. A shared frontend parser detects the block and renders a `ClarifyCard`; on submit, answers are serialized to plain text and sent as a new user message to the same endpoint (loop over existing conversation history). No new backend endpoint or DB state — only prompt additions. The clarify protocol is a separate constant kept OUT of the synced `WORKFLOW_DSL_SYSTEM_PROMPT` so heymweb's `/convert` (one-shot, no planning) is unaffected.

**Tech Stack:** Python 3.11 / FastAPI (backend prompts + pytest), Vue 3 + TypeScript strict (frontend), `jsonrepair` (already a dep).

**Spec:** `docs/superpowers/specs/2026-06-20-assistant-clarifying-questions-design.md`

---

## File Structure

**Backend (modify):**
- `backend/app/services/workflow_dsl_prompt.py` — add top-level `CLARIFY_PROTOCOL_PROMPT` constant; append it inside `build_assistant_prompt()`.
- `backend/app/api/ai_assistant.py` — append `CLARIFY_PROTOCOL_PROMPT` to `CANVAS_ASK_SYSTEM_PROMPT` and `DASHBOARD_CHAT_SYSTEM_PROMPT` assembly.
- `backend/tests/test_clarify_protocol_prompt.py` — NEW test file.

**Frontend (create):**
- `frontend/src/types/clarify.ts` — `ClarifyQuestion`, `ClarifyAnswer` interfaces.
- `frontend/src/utils/parseClarify.ts` — `extractClarifyBlock`, `stripClarifyBlock`, `serializeAnswers`.
- `frontend/src/components/ui/ClarifyCard.vue` — question card UI.

**Frontend (modify):**
- `frontend/src/components/Panels/DebugPanel.vue` — canvas integration.
- `frontend/src/components/Chat/ChatConversation.vue` — chat integration.

---

## Task 1: Backend — `CLARIFY_PROTOCOL_PROMPT` constant + sync-safety test

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py` (add top-level constant near `DASHBOARD_WIDGET_PROMPT_HINT`, line ~4163)
- Test: `backend/tests/test_clarify_protocol_prompt.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_clarify_protocol_prompt.py`:

```python
import re
import unittest
from pathlib import Path

from app.services.workflow_dsl_prompt import (
    CLARIFY_PROTOCOL_PROMPT,
    WORKFLOW_DSL_SYSTEM_PROMPT,
)


class TestClarifyProtocolConstant(unittest.TestCase):
    def test_constant_has_key_instructions(self) -> None:
        text = CLARIFY_PROTOCOL_PROMPT
        self.assertIn("heym-clarify", text)
        self.assertIn("[Plan answers]", text)
        # ambiguous -> don't emit DSL
        self.assertRegex(text.lower(), r"ambiguous")
        self.assertRegex(text.lower(), r"do not (emit|generate|output).{0,20}dsl|json")

    def test_synced_dsl_prompt_stays_clean(self) -> None:
        # heymweb sync extracts only WORKFLOW_DSL_SYSTEM_PROMPT; it must NOT
        # contain the clarify protocol, or /convert would start asking questions.
        self.assertNotIn("heym-clarify", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertNotIn("[Plan answers]", WORKFLOW_DSL_SYSTEM_PROMPT)

    def test_exactly_one_triple_quoted_dsl_block(self) -> None:
        # The heymweb sync regex is non-greedy: a second """ block could shift
        # the captured boundary. Guard the source so the synced text is stable.
        src = Path("app/services/workflow_dsl_prompt.py").read_text(encoding="utf-8")
        matches = re.findall(r'WORKFLOW_DSL_SYSTEM_PROMPT\s*=\s*"""', src)
        self.assertEqual(len(matches), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clarify_protocol_prompt.py -v`
Expected: FAIL with `ImportError: cannot import name 'CLARIFY_PROTOCOL_PROMPT'`.

- [ ] **Step 3: Add the constant**

In `backend/app/services/workflow_dsl_prompt.py`, add this top-level constant immediately before `DASHBOARD_WIDGET_PROMPT_HINT = (` (around line 4163). It is a normal `"""` string but its name is NOT `WORKFLOW_DSL_SYSTEM_PROMPT`, so the heymweb sync regex never matches it:

```python
CLARIFY_PROTOCOL_PROMPT = """

## Clarification Protocol (planning phase)

If the user's request is ambiguous or under-specified (missing trigger, goal, data
source, output format, credentials, or any choice you would otherwise guess), DO NOT emit
a workflow JSON block. Instead, emit exactly ONE fenced block tagged `heym-clarify`
containing a JSON object with a `questions` array, then stop and wait.

Rules for the clarify block:
- Ask at most 3-4 questions. Only ask about things that materially change the workflow.
- Each question: `id` (short slug), `text`, `type` ("single" | "multi" | "text"),
  optional `options` (string array), optional `allowOther` (boolean).
- Use `single` for one choice, `multi` for several, `text` for free input.
- Provide `options` whenever sensible; set `allowOther: true` when a genuine free-form
  answer is plausible.

Example:

```heym-clarify
{"questions": [
  {"id": "trigger", "text": "How should this workflow be triggered?", "type": "single",
   "options": ["Webhook", "Manual", "Scheduled"], "allowOther": true},
  {"id": "outputs", "text": "Which outputs are needed?", "type": "multi",
   "options": ["Email", "Slack", "Database"], "allowOther": true}
]}
```

The user will reply with a message that starts with `[Plan answers]` listing their
choices. After reading it: if the request is now clear, generate the workflow JSON as
usual; if it is still ambiguous, you may emit one more `heym-clarify` block. For requests
that are already clear, skip this protocol entirely and generate the workflow directly.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clarify_protocol_prompt.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + format**

Run: `cd backend && uv run ruff format app/services/workflow_dsl_prompt.py tests/test_clarify_protocol_prompt.py && uv run ruff check app/services/workflow_dsl_prompt.py tests/test_clarify_protocol_prompt.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py backend/tests/test_clarify_protocol_prompt.py
git commit -m "feat: add CLARIFY_PROTOCOL_PROMPT constant (kept out of synced DSL prompt)"
```

---

## Task 2: Backend — inject protocol into the three prompts

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py` — `build_assistant_prompt()` (line ~4185)
- Modify: `backend/app/api/ai_assistant.py` — `CANVAS_ASK_SYSTEM_PROMPT` (line ~77) and `DASHBOARD_CHAT_SYSTEM_PROMPT` assembly
- Test: `backend/tests/test_clarify_protocol_prompt.py` (extend)

- [ ] **Step 1: Extend the failing test**

Append to `backend/tests/test_clarify_protocol_prompt.py`:

```python
from app.api.ai_assistant import (  # noqa: E402
    CANVAS_ASK_SYSTEM_PROMPT,
    DASHBOARD_CHAT_SYSTEM_PROMPT,
)
from app.services.workflow_dsl_prompt import build_assistant_prompt  # noqa: E402


class TestClarifyProtocolInjection(unittest.TestCase):
    def test_build_assistant_prompt_includes_protocol(self) -> None:
        prompt = build_assistant_prompt()
        self.assertIn("heym-clarify", prompt)

    def test_canvas_ask_prompt_includes_protocol(self) -> None:
        self.assertIn("heym-clarify", CANVAS_ASK_SYSTEM_PROMPT)

    def test_dashboard_chat_prompt_includes_protocol(self) -> None:
        self.assertIn("heym-clarify", DASHBOARD_CHAT_SYSTEM_PROMPT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clarify_protocol_prompt.py::TestClarifyProtocolInjection -v`
Expected: FAIL (`heym-clarify` not found in the three prompts).

- [ ] **Step 3a: Append to `build_assistant_prompt()`**

In `backend/app/services/workflow_dsl_prompt.py`, find the `return prompt` at the end of `build_assistant_prompt()` (after the user-rules / available-workflows / node-templates sections). Immediately before that `return prompt`, add:

```python
    prompt += CLARIFY_PROTOCOL_PROMPT
```

(Function-level append — never inside the `WORKFLOW_DSL_SYSTEM_PROMPT` string literal.)

- [ ] **Step 3b: Append to `CANVAS_ASK_SYSTEM_PROMPT`**

In `backend/app/api/ai_assistant.py`, the import block already pulls from `workflow_dsl_prompt`. Add `CLARIFY_PROTOCOL_PROMPT` to that import (the same import that brings in `DASHBOARD_WIDGET_PROMPT_HINT`, line ~65):

```python
    CLARIFY_PROTOCOL_PROMPT,
```

Then, right after the `CANVAS_ASK_SYSTEM_PROMPT = """...\"""` literal ends (line ~134, before `WORKFLOW_ANALYZE_SYSTEM_PROMPT`), add:

```python
CANVAS_ASK_SYSTEM_PROMPT = CANVAS_ASK_SYSTEM_PROMPT + CLARIFY_PROTOCOL_PROMPT
```

- [ ] **Step 3c: Append to `DASHBOARD_CHAT_SYSTEM_PROMPT`**

In `backend/app/api/ai_assistant.py`, right after the `DASHBOARD_CHAT_SYSTEM_PROMPT = """...\"""` literal ends (line ~332+), add:

```python
DASHBOARD_CHAT_SYSTEM_PROMPT = DASHBOARD_CHAT_SYSTEM_PROMPT + CLARIFY_PROTOCOL_PROMPT
```

This covers both the chat surface (`chats.py` imports this constant) and `/ai/dashboard-chat`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clarify_protocol_prompt.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Lint + format**

Run: `cd backend && uv run ruff format app/api/ai_assistant.py app/services/workflow_dsl_prompt.py && uv run ruff check app/api/ai_assistant.py app/services/workflow_dsl_prompt.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/app/services/workflow_dsl_prompt.py backend/tests/test_clarify_protocol_prompt.py
git commit -m "feat: inject clarify protocol into canvas-build, canvas-ask, and chat prompts"
```

---

## Task 3: Frontend — clarify types

**Files:**
- Create: `frontend/src/types/clarify.ts`

- [ ] **Step 1: Create the types file**

```typescript
export type ClarifyQuestionType = "single" | "multi" | "text";

export interface ClarifyQuestion {
  id: string;
  text: string;
  type: ClarifyQuestionType;
  options?: string[];
  allowOther?: boolean;
}

export interface ClarifyPayload {
  questions: ClarifyQuestion[];
}

export interface ClarifyAnswer {
  id: string;
  text: string;
  // For single/multi: the chosen option label(s). For text: empty.
  selected: string[];
  // Free-text entered via "Other" or a text question.
  other: string;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: PASS (no new errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/clarify.ts
git commit -m "feat: clarify question/answer types"
```

---

## Task 4: Frontend — parseClarify util

**Files:**
- Create: `frontend/src/utils/parseClarify.ts`

- [ ] **Step 1: Create the util**

This mirrors `extractWorkflowJson` (`DebugPanel.vue:1461`) but targets the `` ```heym-clarify `` fence and validates the clarify shape. Uses `jsonrepair` (already a dependency, imported in `DebugPanel.vue`).

```typescript
import { jsonrepair } from "jsonrepair";

import type {
  ClarifyAnswer,
  ClarifyPayload,
  ClarifyQuestion,
  ClarifyQuestionType,
} from "@/types/clarify";

const FENCE = "```heym-clarify";

function isValidQuestion(q: unknown): q is ClarifyQuestion {
  if (!q || typeof q !== "object") return false;
  const obj = q as Record<string, unknown>;
  const validType = obj.type === "single" || obj.type === "multi" || obj.type === "text";
  return (
    typeof obj.id === "string" &&
    typeof obj.text === "string" &&
    validType &&
    (obj.options === undefined || Array.isArray(obj.options)) &&
    (obj.allowOther === undefined || typeof obj.allowOther === "boolean")
  );
}

function validate(parsed: unknown): ClarifyQuestion[] | null {
  if (!parsed || typeof parsed !== "object") return null;
  const questions = (parsed as { questions?: unknown }).questions;
  if (!Array.isArray(questions) || questions.length === 0) return null;
  if (!questions.every(isValidQuestion)) return null;
  return questions.map((q) => {
    const obj = q as Record<string, unknown>;
    return {
      id: obj.id as string,
      text: obj.text as string,
      type: obj.type as ClarifyQuestionType,
      options: (obj.options as string[] | undefined) ?? undefined,
      allowOther: (obj.allowOther as boolean | undefined) ?? undefined,
    };
  });
}

function bodyBetweenFences(content: string): string | null {
  const start = content.indexOf(FENCE);
  if (start === -1) return null;
  const afterFence = content.slice(start + FENCE.length);
  const firstNewline = afterFence.search(/\n/);
  const bodyStart = firstNewline >= 0 ? firstNewline + 1 : 0;
  const rest = afterFence.slice(bodyStart);
  const closeIdx = rest.indexOf("```");
  return closeIdx >= 0 ? rest.slice(0, closeIdx).trim() : rest.trim();
}

export function extractClarifyBlock(content: string): ClarifyQuestion[] | null {
  const raw = bodyBetweenFences(content);
  if (!raw) return null;
  try {
    return validate(JSON.parse(raw) as ClarifyPayload);
  } catch {
    try {
      return validate(JSON.parse(jsonrepair(raw)) as ClarifyPayload);
    } catch {
      return null;
    }
  }
}

// Remove the raw clarify fence from text so it is not shown as a code block;
// the ClarifyCard renders the questions instead.
export function stripClarifyBlock(content: string): string {
  const start = content.indexOf(FENCE);
  if (start === -1) return content;
  const afterFence = content.slice(start + FENCE.length);
  const firstNewline = afterFence.search(/\n/);
  const bodyStart = firstNewline >= 0 ? firstNewline + 1 : 0;
  const rest = afterFence.slice(bodyStart);
  const closeIdx = rest.indexOf("```");
  const tail = closeIdx >= 0 ? rest.slice(closeIdx + 3) : "";
  return (content.slice(0, start) + tail).trim();
}

export function serializeAnswers(
  questions: ClarifyQuestion[],
  answers: ClarifyAnswer[],
): string {
  const byId = new Map(answers.map((a) => [a.id, a]));
  const lines = questions.map((q) => {
    const a = byId.get(q.id);
    const parts: string[] = [];
    if (a) {
      if (a.selected.length > 0) parts.push(...a.selected);
      if (a.other.trim()) parts.push(`Other: "${a.other.trim()}"`);
    }
    const value = parts.length > 0 ? parts.join(", ") : "(no answer)";
    return `- ${q.text} → ${value}`;
  });
  return ["[Plan answers]", ...lines].join("\n");
}
```

- [ ] **Step 2: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/parseClarify.ts
git commit -m "feat: parseClarify util (extract/strip/serialize heym-clarify)"
```

---

## Task 5: Frontend — ClarifyCard component

**Files:**
- Create: `frontend/src/components/ui/ClarifyCard.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { computed, reactive } from "vue";

import type { ClarifyAnswer, ClarifyQuestion } from "@/types/clarify";

const props = defineProps<{
  questions: ClarifyQuestion[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: "submit", answers: ClarifyAnswer[]): void;
}>();

const state = reactive<Record<string, ClarifyAnswer>>({});

for (const q of props.questions) {
  state[q.id] = { id: q.id, text: q.text, selected: [], other: "" };
}

function selectSingle(q: ClarifyQuestion, option: string): void {
  if (props.disabled) return;
  state[q.id].selected = [option];
}

function toggleMulti(q: ClarifyQuestion, option: string): void {
  if (props.disabled) return;
  const sel = state[q.id].selected;
  const idx = sel.indexOf(option);
  if (idx >= 0) sel.splice(idx, 1);
  else sel.push(option);
}

function isSelected(q: ClarifyQuestion, option: string): boolean {
  return state[q.id].selected.includes(option);
}

const canSubmit = computed(() => {
  if (props.disabled) return false;
  return props.questions.every((q) => {
    const a = state[q.id];
    return a.selected.length > 0 || a.other.trim().length > 0;
  });
});

function submit(): void {
  if (!canSubmit.value) return;
  emit(
    "submit",
    props.questions.map((q) => ({ ...state[q.id] })),
  );
}
</script>

<template>
  <div class="clarify-card" :class="{ disabled: props.disabled }">
    <div v-for="q in props.questions" :key="q.id" class="clarify-question">
      <div class="clarify-text">{{ q.text }}</div>

      <div v-if="q.type === 'single' || q.type === 'multi'" class="clarify-options">
        <button
          v-for="opt in q.options ?? []"
          :key="opt"
          type="button"
          class="clarify-option"
          :class="{ active: isSelected(q, opt) }"
          :disabled="props.disabled"
          @click="q.type === 'single' ? selectSingle(q, opt) : toggleMulti(q, opt)"
        >
          {{ opt }}
        </button>
      </div>

      <input
        v-if="q.type === 'text' || q.allowOther"
        v-model="state[q.id].other"
        type="text"
        class="clarify-other"
        :placeholder="q.type === 'text' ? 'Your answer' : 'Other…'"
        :disabled="props.disabled"
      />
    </div>

    <button
      type="button"
      class="clarify-submit"
      :disabled="!canSubmit"
      @click="submit"
    >
      Submit answers
    </button>
  </div>
</template>

<style scoped>
.clarify-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  margin-top: 8px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 8px;
  background: var(--card, #fff);
}
.clarify-card.disabled {
  opacity: 0.6;
}
.clarify-question {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.clarify-text {
  font-size: 13px;
  font-weight: 600;
}
.clarify-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.clarify-option {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 999px;
  background: transparent;
  cursor: pointer;
}
.clarify-option.active {
  background: var(--primary, #2563eb);
  color: #fff;
  border-color: var(--primary, #2563eb);
}
.clarify-other {
  padding: 6px 8px;
  font-size: 12px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 6px;
}
.clarify-submit {
  align-self: flex-start;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  border-radius: 6px;
  background: var(--primary, #2563eb);
  color: #fff;
  cursor: pointer;
}
.clarify-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
```

- [ ] **Step 2: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/ClarifyCard.vue
git commit -m "feat: ClarifyCard component (buttons + Other free-text)"
```

---

## Task 6: Frontend — canvas integration (DebugPanel)

**Files:**
- Modify: `frontend/src/components/Panels/DebugPanel.vue`

- [ ] **Step 1: Add imports**

In the `<script setup>` imports of `DebugPanel.vue`, add:

```typescript
import ClarifyCard from "@/components/ui/ClarifyCard.vue";
import type { ClarifyAnswer, ClarifyQuestion } from "@/types/clarify";
import {
  extractClarifyBlock,
  serializeAnswers,
  stripClarifyBlock,
} from "@/utils/parseClarify";
```

- [ ] **Step 2: Extend the `ChatMessage` interface**

At `DebugPanel.vue:1110`, add a `clarify` field:

```typescript
interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  workflowJson?: {
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
  };
  hasParseError?: boolean;
  clarify?: ClarifyQuestion[];
  clarifyAnswered?: boolean;
}
```

(Keep the existing fields exactly; only add the two new optional lines.)

- [ ] **Step 3: Make `sendAiMessage` accept an optional text argument**

Change the signature and the first lines of `sendAiMessage` (`DebugPanel.vue:1501-1503`) from:

```typescript
async function sendAiMessage(): Promise<void> {
  const message = aiInputMessage.value.trim();
```

to:

```typescript
async function sendAiMessage(overrideText?: string): Promise<void> {
  const message = (overrideText ?? aiInputMessage.value).trim();
```

Leave the rest of the function unchanged (it already clears `aiInputMessage.value`, which is harmless when an override is used).

- [ ] **Step 4: Detect clarify block in `onDone`**

In the `onDone` callback of `aiApi.assistantStream` (`DebugPanel.vue:1554-1575`), replace the body that starts at `if (isAskMode) return;` with logic that checks for a clarify block FIRST (clarify wins over DSL). Replace:

```typescript
      if (isAskMode) return;

      const lastMsg = aiMessages.value[aiMessages.value.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        const workflowJson = extractWorkflowJson(lastMsg.content);
        if (workflowJson) {
          lastMsg.workflowJson = workflowJson;
          lastMsg.hasParseError = false;
          playSuccessSound();
          setTimeout(() => {
            applyWorkflowChanges(true);
          }, 300);
        } else if (lastMsg.content.trim().length > 0) {
          lastMsg.hasParseError = true;
        }
      }
```

with:

```typescript
      const lastMsg = aiMessages.value[aiMessages.value.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        const clarify = extractClarifyBlock(lastMsg.content);
        if (clarify) {
          lastMsg.clarify = clarify;
          lastMsg.hasParseError = false;
          return;
        }
      }

      if (isAskMode) return;

      if (lastMsg && lastMsg.role === "assistant") {
        const workflowJson = extractWorkflowJson(lastMsg.content);
        if (workflowJson) {
          lastMsg.workflowJson = workflowJson;
          lastMsg.hasParseError = false;
          playSuccessSound();
          setTimeout(() => {
            applyWorkflowChanges(true);
          }, 300);
        } else if (lastMsg.content.trim().length > 0) {
          lastMsg.hasParseError = true;
        }
      }
```

(The clarify check runs in both ask and build mode; only DSL application is gated by `isAskMode`.)

- [ ] **Step 5: Add the submit handler**

Add this function near `sendAiMessage` in `DebugPanel.vue`:

```typescript
function handleClarifySubmit(msg: ChatMessage, answers: ClarifyAnswer[]): void {
  if (!msg.clarify || msg.clarifyAnswered) return;
  msg.clarifyAnswered = true;
  const serialized = serializeAnswers(msg.clarify, answers);
  void sendAiMessage(serialized);
}
```

- [ ] **Step 6: Render the card + strip raw block in the template**

In the message render block (`DebugPanel.vue:3193-3204`), change the content render to strip the clarify fence, and add the card. Replace:

```vue
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="message-content"
              v-html="renderContent(msg.content)"
            />
            <!-- eslint-enable vue/no-v-html -->
```

with:

```vue
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="message-content"
              v-html="renderContent(msg.clarify ? stripClarifyBlock(msg.content) : msg.content)"
            />
            <!-- eslint-enable vue/no-v-html -->
            <ClarifyCard
              v-if="msg.clarify"
              :questions="msg.clarify"
              :disabled="msg.clarifyAnswered || aiStreaming"
              @submit="(answers) => handleClarifySubmit(msg, answers)"
            />
```

- [ ] **Step 7: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Panels/DebugPanel.vue
git commit -m "feat: render clarify card + planning loop in canvas assistant"
```

---

## Task 7: Frontend — chat integration (ChatConversation)

**Files:**
- Modify: `frontend/src/components/Chat/ChatConversation.vue`

- [ ] **Step 1: Add imports**

In `ChatConversation.vue` `<script setup>`, add:

```typescript
import ClarifyCard from "@/components/ui/ClarifyCard.vue";
import type { ClarifyAnswer, ClarifyQuestion } from "@/types/clarify";
import { extractClarifyBlock, serializeAnswers, stripClarifyBlock } from "@/utils/parseClarify";
```

- [ ] **Step 2: Add a per-message clarify resolver + answered tracking**

The chat store's `Message` type is server-driven, so track clarify state locally by message id. Add near the other refs in `ChatConversation.vue`:

```typescript
const answeredClarify = reactive<Set<string>>(new Set());

function clarifyFor(msg: { id: string; role: string; content: string }): ClarifyQuestion[] | null {
  if (msg.role !== "assistant") return null;
  return extractClarifyBlock(msg.content);
}
```

(Ensure `reactive` is in the existing `vue` import.)

- [ ] **Step 3: Add the submit handler**

Use the exact identifiers from the existing send call site (`ChatConversation.vue:515-521`):
`chatStore` (`:57`), `props.conversationId` (`:48`), `selectedCredentialId` (`:70`),
`selectedModel` (`:71`). The store signature is
`sendMessage(conversationId, content, credentialId, model, attachment?)` (`frontend/src/stores/chat.ts:282`). Add:

```typescript
function handleClarifySubmit(
  msgId: string,
  questions: ClarifyQuestion[],
  answers: ClarifyAnswer[],
): void {
  if (answeredClarify.has(msgId)) return;
  if (!selectedCredentialId.value || !selectedModel.value) return;
  answeredClarify.add(msgId);
  const serialized = serializeAnswers(questions, answers);
  void chatStore.sendMessage(
    props.conversationId,
    serialized,
    selectedCredentialId.value,
    selectedModel.value,
  );
}
```

- [ ] **Step 4: Render the card in the assistant message block**

At the assistant markdown render (`ChatConversation.vue:969-975`), strip the clarify fence and append the card. Replace:

```vue
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="chat-markdown"
              v-html="renderMarkdown(msg.content)"
            />
            <!-- eslint-enable vue/no-v-html -->
```

with:

```vue
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="chat-markdown"
              v-html="renderMarkdown(clarifyFor(msg) ? stripClarifyBlock(msg.content) : msg.content)"
            />
            <!-- eslint-enable vue/no-v-html -->
            <ClarifyCard
              v-if="clarifyFor(msg)"
              :questions="clarifyFor(msg)!"
              :disabled="answeredClarify.has(msg.id)"
              @submit="(answers) => handleClarifySubmit(msg.id, clarifyFor(msg)!, answers)"
            />
```

- [ ] **Step 5: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/ChatConversation.vue
git commit -m "feat: render clarify card + planning loop in chat assistant"
```

---

## Task 8: Full verification

- [ ] **Step 1: Run full check**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: backend ruff + tests pass, frontend lint + typecheck pass. Commit any formatting-only diffs.

- [ ] **Step 2: Manual smoke (canvas)**

Start the app (`./run.sh`), open the editor, open the AI panel in build mode, and send a deliberately vague request (e.g. "build me a notification workflow"). Expected: the assistant returns a `ClarifyCard` with buttons + Other instead of applying DSL. Answer it → the assistant generates and previews the workflow.

- [ ] **Step 3: Manual smoke (chat)**

In the chat surface, send a vague workflow request. Expected: the `ClarifyCard` renders inline; submitting answers continues the conversation and produces the workflow.

- [ ] **Step 4: Sync-safety check (heymweb untouched)**

Run: `cd ../heymweb && bun run sync-dsl-prompt && git diff --stat src/lib/heymDslPrompt.ts`
Expected: NO diff (the synced DSL prompt is byte-identical; clarify protocol stays out of it). If a diff appears, the protocol leaked into `WORKFLOW_DSL_SYSTEM_PROMPT` — fix Task 1/2 placement.

- [ ] **Step 5: Final commit (if any formatting diffs remain)**

```bash
git add -A
git commit -m "chore: formatting for clarify questions feature"
```

> Per user instruction: keep changes LOCAL — do NOT push. Commits are local only.

---

## Notes for the implementer

- **No frontend tests** (project rule): `parseClarify.ts` and `ClarifyCard.vue` are verified by typecheck + lint + manual smoke.
- **Multi-round** is automatic: each answer is a normal user message; the assistant may emit another `heym-clarify` block or the final DSL. No extra state machine needed.
- **Clarify wins over DSL**: if a message somehow contains both blocks, the clarify card is shown and DSL is ignored (the model is signalling it is not yet confident).
- **The hard constraint** (Task 1 placement + Task 8 Step 4) is the load-bearing safety check — heymweb's `/convert` must keep emitting DSL only.
