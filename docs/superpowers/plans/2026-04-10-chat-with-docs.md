# Chat with Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Chat with Docs" magic wand button to the DocsView header that opens a centered dialog where users can select credentials/model and chat with the AI assistant, context-aware of the currently open doc page.

**Architecture:** Single new component `DocsChatDialog.vue` (self-contained: credential/model selection + streaming chat). `DocsView.vue` gets a purple wand button in the `#actions` slot and mounts the dialog. Backend unchanged — reuses `POST /api/ai/dashboard-chat`. Active `docPath` injected via `userRules` param.

**Tech Stack:** Vue 3 Composition API, TypeScript strict, `aiApi.dashboardChatStream`, `credentialsApi.listLLM/getModels`, `marked` + `DOMPurify`, lucide-vue-next (`Wand2`, `ChevronDown`, `Send`, `Square`, `Loader2`), existing `Dialog.vue`.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `frontend/src/components/Docs/DocsChatDialog.vue` | Full dialog: credential/model selects, message list, streaming, input |
| Modify | `frontend/src/views/DocsView.vue` | Add purple wand button + mount `<DocsChatDialog>` |

---

### Task 1: Create `DocsChatDialog.vue` — skeleton with credential/model selection

**Files:**
- Create: `frontend/src/components/Docs/DocsChatDialog.vue`

> No frontend tests exist per AGENTS.md. Manual test checklist at end of each task.

- [ ] **Step 1: Create the file with script setup, props, and credential/model state**

Create `frontend/src/components/Docs/DocsChatDialog.vue` with this exact content:

```vue
<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { ChevronDown, Loader2, Send, Square, Wand2 } from "lucide-vue-next";
import { marked } from "marked";
import DOMPurify from "dompurify";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import { aiApi, credentialsApi } from "@/services/api";
import type { CredentialListItem, LLMModel } from "@/types/credential";

interface Props {
  open: boolean;
  docPath: string | null;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{ (e: "close"): void }>();

const credentials = ref<CredentialListItem[]>([]);
const selectedCredentialId = ref("");
const selectedModel = ref("");
const loadingModels = ref(false);
const models = ref<LLMModel[]>([]);

const messages = ref<ChatMessage[]>([]);
const inputText = ref("");
const streaming = ref(false);
const messagesContainer = ref<HTMLElement | null>(null);
const chatInputRef = ref<HTMLTextAreaElement | null>(null);
const activeAbortController = ref<AbortController | null>(null);
const activeAssistantMessageId = ref<string | null>(null);

const MAX_CONTEXT_MESSAGES = 25;

function pickDefaultModel(modelList: LLMModel[]): string {
  if (modelList.length === 0) return "";
  const lower = (s: string) => (s || "").toLowerCase();
  const isCerebrasGlm = (m: LLMModel) =>
    lower(m.name).includes("cerebras") ||
    lower(m.name).includes("glm") ||
    lower(m.id).includes("cerebras") ||
    lower(m.id).includes("glm");
  const preferred = modelList.filter(isCerebrasGlm);
  return preferred.length > 0
    ? preferred[preferred.length - 1].id
    : modelList[modelList.length - 1].id;
}

async function loadCredentials(): Promise<void> {
  try {
    credentials.value = await credentialsApi.listLLM();
    if (credentials.value.length > 0 && !selectedCredentialId.value) {
      selectedCredentialId.value = credentials.value[0].id;
    }
  } catch {
    credentials.value = [];
  }
}

async function loadModels(): Promise<void> {
  if (!selectedCredentialId.value) {
    models.value = [];
    selectedModel.value = "";
    return;
  }
  loadingModels.value = true;
  try {
    models.value = await credentialsApi.getModels(selectedCredentialId.value);
    if (models.value.length > 0) {
      selectedModel.value = pickDefaultModel(models.value);
    }
  } catch {
    models.value = [];
    selectedModel.value = "";
  } finally {
    loadingModels.value = false;
  }
}

watch(() => selectedCredentialId.value, loadModels);

function scrollToBottom(): void {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTo({
        top: messagesContainer.value.scrollHeight,
        behavior: "smooth",
      });
    }
  });
}

function scrollToBottomImmediate(): void {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
}

watch(() => messages.value.length, scrollToBottom, { flush: "post" });
watch(
  () => messages.value.at(-1)?.content,
  () => {
    if (streaming.value) nextTick(scrollToBottomImmediate);
  },
  { flush: "post" },
);

function renderMarkdown(content: string): string {
  if (!content) return "";
  const html = marked(content, { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      "p", "br", "strong", "em", "u", "s", "code", "pre", "blockquote",
      "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "hr",
      "table", "thead", "tbody", "tr", "th", "td", "img",
    ],
    ALLOWED_ATTR: ["href", "target", "rel", "src", "alt"],
  });
}

function handleSubmit(): void {
  const text = inputText.value.trim();
  if (!text || streaming.value || !selectedCredentialId.value || !selectedModel.value) return;

  const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: text };
  messages.value.push(userMsg);
  inputText.value = "";

  const assistantId = crypto.randomUUID();
  messages.value.push({ id: assistantId, role: "assistant", content: "" });
  activeAssistantMessageId.value = assistantId;
  streaming.value = true;

  const abortController = new AbortController();
  activeAbortController.value = abortController;

  const history = messages.value
    .filter((m) => m.role === "user" || m.role === "assistant")
    .slice(0, -2)
    .slice(-MAX_CONTEXT_MESSAGES)
    .map((m) => ({ role: m.role, content: m.content }));

  const userRules = props.docPath
    ? `The user is currently reading the Heym documentation page: /docs/${props.docPath}. Prioritize answers relevant to this page.`
    : undefined;

  aiApi.dashboardChatStream(
    {
      credentialId: selectedCredentialId.value,
      model: selectedModel.value,
      message: text,
      conversationHistory: history,
      userRules,
      clientLocalDatetime: new Date().toLocaleString(),
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
  );
}

function stopStreaming(): void {
  if (!streaming.value) return;
  activeAbortController.value?.abort();
  streaming.value = false;

  const assistantId = activeAssistantMessageId.value;
  if (assistantId) {
    const index = messages.value.findIndex((msg) => msg.id === assistantId);
    const message = index >= 0 ? messages.value[index] : null;
    if (message && message.role === "assistant" && !message.content.trim()) {
      messages.value.splice(index, 1);
    }
  }
  activeAbortController.value = null;
  activeAssistantMessageId.value = null;
  nextTick(() => chatInputRef.value?.focus());
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    handleSubmit();
  }
}

function handleClose(): void {
  activeAbortController.value?.abort();
  streaming.value = false;
  messages.value = [];
  inputText.value = "";
  activeAbortController.value = null;
  activeAssistantMessageId.value = null;
  emit("close");
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      nextTick(() => chatInputRef.value?.focus());
    } else {
      activeAbortController.value?.abort();
      streaming.value = false;
      messages.value = [];
      inputText.value = "";
      activeAbortController.value = null;
      activeAssistantMessageId.value = null;
    }
  },
);

onMounted(() => {
  loadCredentials();
});

onUnmounted(() => {
  activeAbortController.value?.abort();
});
</script>

<template>
  <Dialog
    :open="open"
    title="Chat with Docs"
    size="2xl"
    :allow-fullscreen="true"
    @close="handleClose"
  >
    <div class="flex flex-col h-[60vh] min-h-0">
      <!-- Credential & Model selection -->
      <div class="flex gap-2 pb-3 border-b border-border/50 shrink-0">
        <div class="relative flex-1 min-w-0">
          <select
            v-model="selectedCredentialId"
            class="w-full h-9 rounded-lg border border-input bg-background pl-3 pr-9 text-sm appearance-none cursor-pointer truncate"
          >
            <option
              value=""
              disabled
            >
              {{ credentials.length === 0 ? "No credentials" : "Select credential..." }}
            </option>
            <option
              v-for="c in credentials"
              :key="c.id"
              :value="c.id"
            >
              {{ c.name }}
            </option>
          </select>
          <ChevronDown class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        </div>
        <div class="relative flex-1 min-w-0">
          <select
            v-model="selectedModel"
            :disabled="!selectedCredentialId || loadingModels"
            class="w-full h-9 rounded-lg border border-input bg-background pl-3 pr-9 text-sm appearance-none cursor-pointer disabled:opacity-50 truncate"
          >
            <option
              value=""
              disabled
            >
              {{ loadingModels ? "Loading..." : "Select model..." }}
            </option>
            <option
              v-for="m in models"
              :key="m.id"
              :value="m.id"
            >
              {{ m.name }}
            </option>
          </select>
          <ChevronDown class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        </div>
      </div>

      <!-- Messages area -->
      <div
        ref="messagesContainer"
        :class="[
          'flex-1 min-h-0 overflow-y-auto py-4 space-y-3',
          messages.length === 0 && 'flex flex-col items-center justify-center',
        ]"
      >
        <div
          v-if="messages.length === 0"
          class="flex flex-col items-center gap-3 text-muted-foreground text-center px-4"
        >
          <Wand2 class="w-10 h-10 opacity-40" />
          <p class="text-sm">
            Ask anything about the docs
          </p>
        </div>
        <template v-else>
          <div
            v-for="msg in messages"
            :key="msg.id"
            :class="['flex', msg.role === 'user' ? 'justify-end' : 'justify-start']"
          >
            <div
              :class="[
                'max-w-[85%] rounded-2xl px-4 py-3 text-sm break-words',
                msg.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted/80 border border-border/50',
              ]"
            >
              <template v-if="msg.role === 'assistant'">
                <!-- eslint-disable vue/no-v-html -->
                <div
                  v-if="msg.content"
                  class="markdown-content prose prose-sm dark:prose-invert max-w-none break-words"
                  v-html="renderMarkdown(msg.content)"
                />
                <!-- eslint-enable vue/no-v-html -->
                <div
                  v-else-if="streaming && messages.at(-1)?.id === msg.id"
                  class="flex items-center gap-2 text-muted-foreground"
                >
                  <Loader2 class="w-4 h-4 animate-spin shrink-0" />
                  <span>Thinking...</span>
                </div>
              </template>
              <p
                v-else
                class="whitespace-pre-wrap overflow-wrap-anywhere"
              >
                {{ msg.content }}
              </p>
            </div>
          </div>
        </template>
      </div>

      <!-- Context badge + Input -->
      <div class="shrink-0 pt-3 border-t border-border/50">
        <div
          v-if="docPath"
          class="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground"
        >
          <span>📄</span>
          <span class="font-mono">{{ docPath }}</span>
        </div>
        <form
          class="flex items-center gap-2 rounded-2xl bg-muted/40 border border-border/40 px-3 py-2 min-h-[52px] focus-within:border-primary/30 transition-colors"
          @submit.prevent="handleSubmit"
        >
          <textarea
            ref="chatInputRef"
            v-model="inputText"
            :disabled="streaming || !selectedCredentialId || !selectedModel"
            placeholder="Ask about the docs..."
            rows="1"
            class="flex-1 min-h-[36px] max-h-32 resize-none bg-transparent border-0 px-1 py-2 text-sm focus:outline-none disabled:opacity-50 placeholder:text-muted-foreground leading-5"
            @keydown="handleKeydown"
          />
          <Button
            v-if="!streaming"
            type="submit"
            variant="gradient"
            size="icon"
            :disabled="!inputText.trim() || !selectedCredentialId || !selectedModel"
            class="shrink-0 h-9 w-9 rounded-xl"
          >
            <Send class="w-4 h-4" />
          </Button>
          <Button
            v-else
            type="button"
            variant="destructive"
            size="icon"
            class="shrink-0 h-9 w-9 rounded-xl"
            @click="stopStreaming"
          >
            <Square class="w-4 h-4" />
          </Button>
        </form>
      </div>
    </div>
  </Dialog>
</template>

<style scoped>
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  font-weight: 600;
  margin-top: 0.75em;
  margin-bottom: 0.4em;
}
.markdown-content :deep(p) {
  margin-top: 0.4em;
  margin-bottom: 0.4em;
}
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin-top: 0.4em;
  padding-left: 1.5em;
}
.markdown-content :deep(code) {
  background: hsl(var(--muted) / 0.6);
  padding: 0.125em 0.375em;
  border-radius: 0.25rem;
  font-size: 0.875em;
}
.markdown-content :deep(pre) {
  background: hsl(var(--muted) / 0.6);
  padding: 0.75em;
  border-radius: 0.5rem;
  overflow-x: auto;
  margin-top: 0.5em;
}
.markdown-content :deep(pre code) {
  background: transparent;
  padding: 0;
}
.markdown-content :deep(a) {
  color: hsl(var(--primary));
  text-decoration: underline;
}
.overflow-wrap-anywhere {
  overflow-wrap: anywhere;
  word-break: break-word;
}
</style>
```

- [ ] **Step 2: Run typecheck to verify no type errors**

```bash
cd frontend && bun run typecheck
```

Expected: 0 errors. If errors appear, fix type mismatches (e.g. `CredentialListItem` or `LLMModel` import paths).

- [ ] **Step 3: Run linter**

```bash
cd frontend && bun run lint
```

Expected: 0 errors, 0 warnings. Fix any reported issues before continuing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Docs/DocsChatDialog.vue
git commit -m "feat: add DocsChatDialog component for Chat with Docs"
```

---

### Task 2: Wire `DocsChatDialog` into `DocsView.vue`

**Files:**
- Modify: `frontend/src/views/DocsView.vue`

- [ ] **Step 1: Add the import at the top of `<script setup>` in `DocsView.vue`**

In `frontend/src/views/DocsView.vue`, find the existing import block (around lines 2–22). Add these two lines after the existing imports:

```ts
import { Wand2 } from "lucide-vue-next";
import DocsChatDialog from "@/components/Docs/DocsChatDialog.vue";
```

The full import block should now include (among others):
```ts
import { Github, History, Menu, Wand2 } from "lucide-vue-next";
import DocsChatDialog from "@/components/Docs/DocsChatDialog.vue";
```

- [ ] **Step 2: Add `docsChatOpen` ref**

In `DocsView.vue` script setup, after the existing `ref` declarations (around line 26–28), add:

```ts
const docsChatOpen = ref(false);
```

- [ ] **Step 3: Register `docsChatOpen` with the overlay dismiss handler**

In `DocsView.vue`, find the `onDismissOverlays` call inside `onMounted` (around line 46–50):

```ts
const unsub = onDismissOverlays(() => {
  showCommandPalette.value = false;
  historyOpen.value = false;
  mobileDrawerOpen.value = false;
});
```

Change it to:

```ts
const unsub = onDismissOverlays(() => {
  showCommandPalette.value = false;
  historyOpen.value = false;
  mobileDrawerOpen.value = false;
  docsChatOpen.value = false;
});
```

- [ ] **Step 4: Add the purple "Chat with Docs" button in the `#actions` slot**

In `DocsView.vue` template, find the `<template #actions>` block (around lines 135–156). It currently starts with the GitHub `<a>` link. Add the wand button **before** the GitHub link:

```html
<template #actions>
  <button
    class="inline-flex items-center justify-center gap-1.5 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-sm font-medium transition-all duration-250 active:scale-[0.97] min-h-[44px] min-w-[44px] md:min-h-[36px] md:h-9 px-3"
    title="Chat with Docs"
    aria-label="Chat with Docs"
    @click="docsChatOpen = true; pushOverlayState()"
  >
    <Wand2 class="w-4 h-4 shrink-0" />
    <span class="hidden sm:inline text-xs font-medium">Chat with Docs</span>
  </button>
  <a
    href="https://github.com/heymrun/heym"
    ...existing GitHub link...
  >
```

Keep the rest of the `#actions` slot unchanged.

- [ ] **Step 5: Mount `<DocsChatDialog>` in the template**

In `DocsView.vue` template, find where `<ExecutionHistoryAllDialog>` is mounted (around line 210–213). Add `<DocsChatDialog>` directly after it:

```html
      <ExecutionHistoryAllDialog
        :open="historyOpen"
        @close="historyOpen = false"
      />

      <DocsChatDialog
        :open="docsChatOpen"
        :doc-path="docPath"
        @close="docsChatOpen = false"
      />
    </div>
  </WorkspaceShell>
</template>
```

- [ ] **Step 6: Run typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: 0 errors.

- [ ] **Step 7: Run linter**

```bash
cd frontend && bun run lint
```

Expected: 0 errors.

- [ ] **Step 8: Manual smoke test**

Start the dev server:
```bash
cd frontend && bun run dev
```

Navigate to `http://localhost:4017/docs`. Check:
- [ ] Purple "Chat with Docs" button visible in header (icon-only on mobile <640px, icon + text on desktop)
- [ ] Clicking button opens dialog centered on screen
- [ ] Dialog has "Chat with Docs" title
- [ ] Credential and model dropdowns populate
- [ ] Backdrop click closes dialog (messages cleared)
- [ ] Escape key closes dialog (messages cleared)
- [ ] X button closes dialog (messages cleared)
- [ ] Navigate to `/docs/nodes/llm-node` → open dialog → context badge shows `nodes/llm-node`
- [ ] On docs home `/docs` → open dialog → no context badge shown
- [ ] Send a message, verify streaming works and response renders markdown
- [ ] Stop button aborts mid-stream (empty bubble removed)
- [ ] Close dialog mid-stream → no console errors

- [ ] **Step 9: Commit**

```bash
git add frontend/src/views/DocsView.vue
git commit -m "feat: wire Chat with Docs button and dialog into DocsView"
```

---

### Task 3: Final lint + typecheck pass

- [ ] **Step 1: Full lint and typecheck**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: 0 errors in both.

- [ ] **Step 2: Build check**

```bash
cd frontend && bun run build
```

Expected: build completes with no errors.

- [ ] **Step 3: Final commit if any fixes were needed**

If lint/typecheck/build required any fixes:
```bash
git add -p  # stage only the fix files
git commit -m "fix: lint and typecheck fixes for chat-with-docs"
```

If nothing was needed, skip this step.

---

## Self-Review Checklist

- [x] **Spec coverage:** Button (wand icon, purple bg, mobile icon-only) ✓ — Task 2 Step 4. Dialog (credential/model at top, message area, context badge, input) ✓ — Task 1. Close on backdrop/Escape/X ✓ — handled by `Dialog.vue` + `handleClose`. Session-only messages (reset on close) ✓ — `handleClose` and `watch(props.open)`. docPath context injection via `userRules` ✓ — `handleSubmit`. Zero backend changes ✓.
- [x] **Placeholder scan:** No TBDs or TODOs in any step. All code blocks are complete.
- [x] **Type consistency:** `ChatMessage`, `pickDefaultModel`, `loadCredentials`, `loadModels`, `handleSubmit`, `stopStreaming`, `handleClose` all defined in Task 1 and not referenced from other tasks under different names.
