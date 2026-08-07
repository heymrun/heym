# Dashboard Chat Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a horizontal chat composer to the top of the dashboard Workflows tab that greets the user, takes a prompt plus an optional file, lets them pick an LLM credential and model, then creates a conversation and opens it in the chat tab with the reply already streaming.

**Architecture:** A new self-contained `DashboardChatComposer.vue` sends through the existing `useChatStore` (`createConversation` then `sendMessage`) and navigates to `/chats/:id`. The credential and model bootstrap that lives inline in `ChatConversation.vue` today is extracted into a shared `useChatModelSelection` composable so both surfaces use one implementation. No backend change.

**Tech Stack:** Vue 3 `<script setup>` + TypeScript strict, Pinia, Vue Router, Tailwind, existing `SearchableSelect` and `useFileAttachment`.

**Spec:** `docs/superpowers/specs/2026-08-07-dashboard-chat-composer-design.md`

---

## Testing policy for this plan

This repo's owner does not want frontend or UI tests written for heymrun (verification is lint, typecheck, and manual checks). This feature is frontend only and touches no backend code, so there are no pytest additions either. That is why the tasks below do not follow the usual red/green TDD loop. Every task still ends with a mechanical verification command whose expected output is stated, plus a manual check where behavior changes.

Run all frontend commands from `frontend/`:

- `bun run lint`
- `bun run typecheck`

Run `./check.sh` from the repo root once at the end (it applies `ruff format`, then lint and backend tests). If your shell does not export `SECRET_KEY`, use:
`SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh`

## File structure

| File | Responsibility |
| --- | --- |
| `frontend/src/composables/useChatModelSelection.ts` (create) | Loads LLM credentials and models, resolves defaults through `useAiDefaults`, owns `selectedCredentialId` / `selectedModel` and their loading and failure flags |
| `frontend/src/components/Chat/DashboardChatComposer.vue` (create) | The dashboard composer UI and its submit flow |
| `frontend/src/components/Chat/ChatConversation.vue` (modify) | Drops its inline credential and model state in favor of the composable |
| `frontend/src/views/DashboardView.vue` (modify) | Renders the composer on the Workflows tab, owns the dismissed flag and the `Ask AI` restore button |

---

### Task 1: Extract the credential and model selection composable

**Files:**
- Create: `frontend/src/composables/useChatModelSelection.ts`

Background for someone new to this codebase: `credentialsApi.listLLM()` returns the user's LLM credentials, `credentialsApi.getModels(credentialId)` returns the models for one credential, and `useAiDefaults()` resolves the user's preferred credential and model (`preferred_credential_id`, `preferred_model` on the user record). The resolution order copied below is the behavior that ships today in `ChatConversation.vue`; do not change it.

`onModelsSettled` exists because `ChatConversation.vue` runs two side effects in the `finally` block of its current `loadModels`: it refocuses the chat textarea and it loads the context summary. The composable stays unaware of those by taking a callback.

- [ ] **Step 1: Create the composable**

```typescript
import { computed, ref } from "vue";
import type { ComputedRef, Ref } from "vue";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import { useAiDefaults } from "@/composables/useAiDefaults";
import { credentialsApi } from "@/services/api";

export interface ChatSelectOption {
  value: string;
  label: string;
}

export interface SavedChatSelection {
  credentialId?: string | null;
  model?: string | null;
}

export interface UseChatModelSelectionOptions {
  /** Runs after every model load attempt, success or failure. */
  onModelsSettled?: () => void;
}

export interface UseChatModelSelectionResult {
  credentials: Ref<CredentialListItem[]>;
  models: Ref<LLMModel[]>;
  selectedCredentialId: Ref<string>;
  selectedModel: Ref<string>;
  credentialOptions: ComputedRef<ChatSelectOption[]>;
  modelOptions: ComputedRef<ChatSelectOption[]>;
  isLoadingModels: Ref<boolean>;
  modelsLoadFailed: Ref<boolean>;
  credentialError: Ref<string>;
  credentialsLoaded: Ref<boolean>;
  hasCredentials: ComputedRef<boolean>;
  isReady: ComputedRef<boolean>;
  modelPlaceholder: ComputedRef<string>;
  loadCredentials: () => Promise<void>;
  loadModels: (credentialId: string, preferredModelId?: string) => Promise<void>;
  applySavedSelection: (saved?: SavedChatSelection) => Promise<void>;
  selectCredential: (value: string | undefined) => Promise<void>;
  bootstrap: (saved?: SavedChatSelection) => Promise<void>;
}

/**
 * Shared LLM credential and model selection for chat surfaces.
 *
 * Resolution order matches the chat composer: a saved selection wins, then the
 * user's preferred credential and model, then the first credential and the last
 * model in the list.
 */
export function useChatModelSelection(
  options: UseChatModelSelectionOptions = {},
): UseChatModelSelectionResult {
  const aiDefaults = useAiDefaults();

  const credentials = ref<CredentialListItem[]>([]);
  const models = ref<LLMModel[]>([]);
  const selectedCredentialId = ref("");
  const selectedModel = ref("");
  const isLoadingModels = ref(false);
  const modelsLoadFailed = ref(false);
  const credentialError = ref("");
  const credentialsLoaded = ref(false);

  const credentialOptions = computed<ChatSelectOption[]>(() =>
    credentials.value.map((credential) => ({
      value: credential.id,
      label: credential.name,
    })),
  );

  const modelOptions = computed<ChatSelectOption[]>(() =>
    models.value.map((model) => ({
      value: model.id,
      label: model.name,
    })),
  );

  const hasCredentials = computed<boolean>(() => credentials.value.length > 0);

  const isReady = computed<boolean>(
    () =>
      Boolean(selectedCredentialId.value) &&
      Boolean(selectedModel.value) &&
      !modelsLoadFailed.value,
  );

  const modelPlaceholder = computed<string>(() => {
    if (isLoadingModels.value) return "Loading...";
    if (modelsLoadFailed.value) return "Failed to load";
    return "Select...";
  });

  async function loadModels(credentialId: string, preferredModelId?: string): Promise<void> {
    if (!credentialId) return;
    isLoadingModels.value = true;
    modelsLoadFailed.value = false;
    models.value = [];
    selectedModel.value = "";
    try {
      models.value = await credentialsApi.getModels(credentialId);
      if (models.value.length > 0) {
        const match = preferredModelId
          ? models.value.find((model) => model.id === preferredModelId)
          : null;
        const preferredModel = aiDefaults.resolveModel(credentialId, models.value, {
          savedModel: preferredModelId ?? null,
        });
        selectedModel.value =
          preferredModel ?? (match ? match.id : models.value[models.value.length - 1].id);
      }
    } catch {
      modelsLoadFailed.value = true;
    } finally {
      isLoadingModels.value = false;
      options.onModelsSettled?.();
    }
  }

  async function loadCredentials(): Promise<void> {
    try {
      credentials.value = await credentialsApi.listLLM();
      credentialsLoaded.value = true;
    } catch {
      credentialError.value = "Failed to load credentials";
    }
  }

  async function applySavedSelection(saved: SavedChatSelection = {}): Promise<void> {
    if (credentials.value.length === 0) return;
    const savedCredentialId = saved.credentialId ?? null;
    if (savedCredentialId && credentials.value.some((c) => c.id === savedCredentialId)) {
      selectedCredentialId.value = savedCredentialId;
      await loadModels(savedCredentialId, saved.model ?? undefined);
      return;
    }
    if (selectedCredentialId.value) return;
    const resolved = aiDefaults.resolveCredentialId(credentials.value, {});
    if (!resolved) return;
    selectedCredentialId.value = resolved;
    await loadModels(resolved);
  }

  async function selectCredential(value: string | undefined): Promise<void> {
    selectedCredentialId.value = value ?? "";
    if (!selectedCredentialId.value) {
      models.value = [];
      selectedModel.value = "";
      return;
    }
    await loadModels(selectedCredentialId.value);
  }

  async function bootstrap(saved: SavedChatSelection = {}): Promise<void> {
    await loadCredentials();
    await applySavedSelection(saved);
  }

  return {
    credentials,
    models,
    selectedCredentialId,
    selectedModel,
    credentialOptions,
    modelOptions,
    isLoadingModels,
    modelsLoadFailed,
    credentialError,
    credentialsLoaded,
    hasCredentials,
    isReady,
    modelPlaceholder,
    loadCredentials,
    loadModels,
    applySavedSelection,
    selectCredential,
    bootstrap,
  };
}
```

- [ ] **Step 2: Verify it compiles**

Run from `frontend/`: `bun run typecheck`
Expected: PASS, no output errors. The composable is not imported anywhere yet, and `noUnusedLocals` only flags unused locals inside a module, not unused exports, so this is clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/composables/useChatModelSelection.ts
git commit -m "refactor: add shared useChatModelSelection composable"
```

---

### Task 2: Move ChatConversation onto the composable

**Files:**
- Modify: `frontend/src/components/Chat/ChatConversation.vue`

This task must be behavior preserving. The chat view is the primary chat surface and a regression here is worse than the whole feature.

- [ ] **Step 1: Replace the imports**

In the import block, delete the `CredentialListItem, LLMModel` type import and the `useAiDefaults` import, and add the composable. Concretely:

Remove these two lines:

```typescript
import type { CredentialListItem, LLMModel } from "@/types/credential";
```

```typescript
import { useAiDefaults } from "@/composables/useAiDefaults";
```

Add next to the other composable imports:

```typescript
import { useChatModelSelection } from "@/composables/useChatModelSelection";
```

Also change the API import from:

```typescript
import { aiApi, credentialsApi } from "@/services/api";
```

to:

```typescript
import { aiApi } from "@/services/api";
```

- [ ] **Step 2: Replace the local state block**

Delete these declarations (they currently sit just after `const fileInputRef = ...`):

```typescript
const credentials = ref<CredentialListItem[]>([]);
const models = ref<LLMModel[]>([]);
const selectedCredentialId = ref("");
const selectedModel = ref("");
const isLoadingModels = ref(false);
const credentialError = ref("");
const modelsLoadFailed = ref(false);
```

Delete the `credentialOptions`, `modelOptions`, and `modelSelectPlaceholder` computed blocks, and delete the local `interface SelectOption { value: string; label: string; }` near the top of the script. Those two computeds are its only consumers, so nothing else breaks.

Do not destructure `models` or `loadModels` from the composable. After this refactor nothing in `ChatConversation.vue` references them directly, and `noUnusedLocals` would fail the typecheck.

Delete `const aiDefaults = useAiDefaults();`.

In their place, add:

```typescript
const {
  credentials,
  selectedCredentialId,
  selectedModel,
  credentialOptions,
  modelOptions,
  isLoadingModels,
  modelsLoadFailed,
  credentialError,
  modelPlaceholder: modelSelectPlaceholder,
  loadCredentials: loadCredentialList,
  applySavedSelection,
  selectCredential,
} = useChatModelSelection({
  onModelsSettled: () => {
    focusInputWhenReady();
    void _maybeLoadContextSummary();
  },
});
```

Note: `focusInputWhenReady` and `_maybeLoadContextSummary` are function declarations later in the file, so they are hoisted and safe to reference from this callback.

- [ ] **Step 3: Rewrite the three functions that used the deleted state**

Replace the existing `_applyConversationSession`, `loadCredentials`, and `loadModels` function bodies with these. The old `loadModels` and the old `onCredentialChange` are deleted entirely; `loadModels` now comes from the composable.

```typescript
function _applyConversationSession(): void {
  const conv = chatStore.activeConversation;
  if (!conv || !credentials.value.length) return;
  void applySavedSelection({
    credentialId: conv.last_credential_id,
    model: conv.last_model,
  });
}

async function loadCredentials(): Promise<void> {
  await loadCredentialList();
  _credentialsReady = true;
  if (credentials.value.length === 0) return;
  if (chatStore.activeConversation) {
    _applyConversationSession();
    return;
  }
  await applySavedSelection();
}

function onCredentialSelect(value: string | undefined): void {
  void selectCredential(value);
}
```

Delete the old `async function onCredentialChange()` since `selectCredential` covers it. Search the file for `onCredentialChange` first and make sure the template does not reference it (today only `onCredentialSelect` is bound).

- [ ] **Step 4: Confirm nothing else referenced the removed symbols**

Run from `frontend/`:

```bash
grep -n "aiDefaults\|credentialsApi\|onCredentialChange\|LLMModel" src/components/Chat/ChatConversation.vue
```

Expected: no matches. If `credentialsApi` still matches, some other call site uses it; keep the import and only drop the unused symbols.

- [ ] **Step 5: Lint and typecheck**

Run from `frontend/`: `bun run lint && bun run typecheck`
Expected: both PASS with no errors.

- [ ] **Step 6: Manual smoke test of the chat view**

Start the stack from the repo root with `./run.sh`, open `http://localhost:4017/chats`, then check:

1. Opening an existing conversation preselects that conversation's credential and model.
2. Creating a new chat preselects your preferred credential and model.
3. Switching the credential dropdown reloads the model list.
4. Sending a message still works and streams.

Expected: identical to `main` before this change.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Chat/ChatConversation.vue
git commit -m "refactor: use shared model selection composable in ChatConversation"
```

---

### Task 3: Build the DashboardChatComposer component

**Files:**
- Create: `frontend/src/components/Chat/DashboardChatComposer.vue`

The component is not mounted anywhere in this task, so it can be reviewed on its own before it touches the dashboard.

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Loader2, Paperclip, Send, X } from "lucide-vue-next";

import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { useChatModelSelection } from "@/composables/useChatModelSelection";
import { useFileAttachment } from "@/composables/useFileAttachment";
import { useAuthStore } from "@/stores/auth";
import { useChatStore } from "@/stores/chat";

const emit = defineEmits<{
  (event: "dismiss"): void;
  (event: "open-credentials"): void;
}>();

const ATTACHMENT_ACCEPT =
  ".txt,.csv,.json,.md,.py,.ts,.js,.html,.xml,.yaml,.yml,.log,.jpg,.jpeg,.png,.gif,.webp,.pdf";
const MAX_INPUT_HEIGHT_PX = 140;

const router = useRouter();
const authStore = useAuthStore();
const chatStore = useChatStore();

const {
  credentialOptions,
  modelOptions,
  selectedCredentialId,
  selectedModel,
  isLoadingModels,
  modelsLoadFailed,
  credentialsLoaded,
  hasCredentials,
  isReady,
  modelPlaceholder,
  bootstrap,
  selectCredential,
} = useChatModelSelection();

const { attachedFile, attachmentError, attachmentLoading, processFile, clearAttachment } =
  useFileAttachment();

const input = ref("");
const inputRef = ref<HTMLTextAreaElement | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const isSubmitting = ref(false);
const submitError = ref("");

const greeting = computed<string>(() => {
  const name = authStore.user?.name?.trim();
  return name ? `Welcome ${name},` : "Welcome,";
});

const showNoCredentialsHint = computed<boolean>(
  () => credentialsLoaded.value && !hasCredentials.value,
);

const canSubmit = computed<boolean>(
  () =>
    input.value.trim().length > 0 &&
    isReady.value &&
    !attachmentLoading.value &&
    attachmentError.value === null &&
    !isSubmitting.value,
);

function resizeInput(): void {
  const element = inputRef.value;
  if (!element) return;
  element.style.height = "auto";
  element.style.height = `${Math.min(element.scrollHeight, MAX_INPUT_HEIGHT_PX)}px`;
}

function onInput(): void {
  resizeInput();
}

function openFilePicker(): void {
  fileInputRef.value?.click();
}

async function handleFileInputChange(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  await processFile(file);
  // Allow re-picking the same file after removing it.
  target.value = "";
}

function onCredentialSelect(value: string | undefined): void {
  void selectCredential(value);
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void submit();
  }
}

async function submit(): Promise<void> {
  const text = input.value.trim();
  if (!canSubmit.value || !text) return;

  isSubmitting.value = true;
  submitError.value = "";
  const payload = attachedFile.value;

  try {
    const conversation = await chatStore.createConversation();
    // sendMessage swallows its own transport errors and clears stream state,
    // so a failure here still leaves a real conversation to navigate to.
    await chatStore.sendMessage(
      conversation.id,
      text,
      selectedCredentialId.value,
      selectedModel.value,
      payload ? { name: payload.name, kind: payload.kind, content: payload.content } : null,
    );
    input.value = "";
    clearAttachment();
    void nextTick(resizeInput);
    await router.push(`/chats/${conversation.id}`);
  } catch {
    submitError.value = "Could not start chat. Try again.";
  } finally {
    isSubmitting.value = false;
  }
}

onMounted(() => {
  void bootstrap();
});
</script>

<template>
  <section
    data-testid="dashboard-chat-composer"
    class="relative z-10 mb-5 rounded-2xl border border-border/50 bg-card/60 px-4 py-4 shadow-sm sm:px-5"
  >
    <button
      type="button"
      class="absolute right-3 top-3 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      aria-label="Hide chat box"
      title="Hide"
      @click="emit('dismiss')"
    >
      <X class="h-4 w-4" />
    </button>

    <h2 class="text-lg font-bold tracking-tight sm:text-xl">
      {{ greeting }}
    </h2>
    <p class="mt-0.5 text-sm text-muted-foreground">
      What do you want to automate?
    </p>

    <input
      ref="fileInputRef"
      type="file"
      :accept="ATTACHMENT_ACCEPT"
      class="hidden"
      @change="handleFileInputChange"
    >

    <form
      class="mt-3 flex flex-col gap-2 rounded-2xl border border-border/40 bg-muted/40 px-2 py-2 transition-colors focus-within:border-primary/30 focus-within:bg-muted/50 sm:flex-row sm:items-center sm:px-3"
      @submit.prevent="submit"
    >
      <button
        type="button"
        class="hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground disabled:pointer-events-none disabled:opacity-50 sm:flex"
        :disabled="attachmentLoading"
        title="Attach file"
        aria-label="Attach file"
        @click="openFilePicker"
      >
        <Paperclip class="h-4 w-4" />
      </button>

      <textarea
        ref="inputRef"
        v-model="input"
        rows="1"
        data-testid="dashboard-chat-input"
        placeholder="Ask anything, or describe a workflow to build"
        class="min-h-[36px] w-full flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground"
        @input="onInput"
        @keydown="onKeydown"
      />

      <div class="flex items-center gap-2">
        <button
          type="button"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground disabled:pointer-events-none disabled:opacity-50 sm:hidden"
          :disabled="attachmentLoading"
          title="Attach file"
          aria-label="Attach file"
          @click="openFilePicker"
        >
          <Paperclip class="h-4 w-4" />
        </button>

        <div
          class="min-w-0 flex-1 sm:w-[160px] sm:flex-none"
          data-testid="dashboard-chat-credential-selector"
        >
          <SearchableSelect
            id="dashboard-chat-credential-select"
            :model-value="selectedCredentialId"
            :options="credentialOptions"
            placeholder="Select..."
            search-placeholder="Search credentials..."
            empty-text="No credentials found."
            :disabled="!hasCredentials"
            select-class="h-9 rounded-lg border-input bg-background shadow-none"
            content-class="z-[60]"
            @update:model-value="onCredentialSelect"
          />
        </div>

        <div
          class="min-w-0 flex-1 sm:w-[160px] sm:flex-none"
          data-testid="dashboard-chat-model-selector"
        >
          <SearchableSelect
            id="dashboard-chat-model-select"
            :model-value="selectedModel"
            :options="modelOptions"
            :placeholder="modelPlaceholder"
            search-placeholder="Search models..."
            empty-text="No models found."
            :disabled="!selectedCredentialId || isLoadingModels || modelsLoadFailed"
            select-class="h-9 rounded-lg border-input bg-background shadow-none"
            content-class="z-[60]"
            @update:model-value="selectedModel = $event ?? ''"
          />
        </div>

        <button
          type="submit"
          data-testid="dashboard-chat-send"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
          :disabled="!canSubmit"
          title="Start chat"
          aria-label="Start chat"
        >
          <Loader2
            v-if="isSubmitting"
            class="h-4 w-4 animate-spin"
          />
          <Send
            v-else
            class="h-4 w-4"
          />
        </button>
      </div>
    </form>

    <div
      v-if="attachedFile || attachmentError || modelsLoadFailed || showNoCredentialsHint || submitError"
      class="mt-2 flex flex-wrap items-center gap-2"
    >
      <div
        v-if="attachedFile"
        class="flex max-w-xs items-center gap-1.5 rounded-lg border border-border/40 bg-muted/60 px-2.5 py-1 text-xs text-foreground"
      >
        <Paperclip class="h-3 w-3 shrink-0 text-muted-foreground" />
        <span class="truncate">{{ attachedFile.name }}</span>
        <span class="shrink-0 text-muted-foreground">· {{ attachedFile.sizeKb }} KB</span>
        <button
          type="button"
          class="ml-0.5 shrink-0 rounded p-0.5 hover:bg-muted/80"
          aria-label="Remove attachment"
          @click="clearAttachment"
        >
          <X class="h-3 w-3" />
        </button>
      </div>

      <p
        v-if="attachmentError"
        class="text-xs text-destructive"
      >
        {{ attachmentError }}
      </p>

      <p
        v-if="modelsLoadFailed"
        class="text-xs text-amber-600 dark:text-amber-400"
      >
        This credential's model list could not be loaded.
      </p>

      <button
        v-if="showNoCredentialsHint"
        type="button"
        class="text-xs font-medium text-primary underline-offset-2 hover:underline"
        @click="emit('open-credentials')"
      >
        Add an LLM credential to start chatting
      </button>

      <p
        v-if="submitError"
        class="text-xs text-destructive"
      >
        {{ submitError }}
      </p>
    </div>
  </section>
</template>
```

- [ ] **Step 2: Check the SearchableSelect props actually exist**

Run from `frontend/`:

```bash
grep -n "defineProps\|withDefaults" -A 20 src/components/ui/SearchableSelect.vue | head -40
```

Expected: props include `modelValue`, `options`, `placeholder`, `searchPlaceholder`, `emptyText`, `disabled`, `selectClass`, `contentClass`, and it emits `update:modelValue`. If any prop name differs, adjust the two `SearchableSelect` usages above to match, and mirror whatever `ChatConversation.vue` already passes.

- [ ] **Step 3: Lint and typecheck**

Run from `frontend/`: `bun run lint && bun run typecheck`
Expected: both PASS. If lint complains that `ATTACHMENT_ACCEPT` or `MAX_INPUT_HEIGHT_PX` are unused, you dropped a template binding; re-add it.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/DashboardChatComposer.vue
git commit -m "feat: add dashboard chat composer component"
```

---

### Task 4: Mount the composer on the dashboard Workflows tab

**Files:**
- Modify: `frontend/src/views/DashboardView.vue`

- [ ] **Step 1: Add the imports**

Add `Sparkles` to the existing `lucide-vue-next` import list (keep it alphabetical, so between `Settings` and `Trash2`):

```typescript
  Settings,
  Sparkles,
  Trash2,
```

Add the component import next to the other `@/components` imports (after the `CredentialsPanel` line reads well alphabetically, but any spot in that block is fine):

```typescript
import DashboardChatComposer from "@/components/Chat/DashboardChatComposer.vue";
```

- [ ] **Step 2: Add the dismiss state**

Add this near the other top-level state in `<script setup>`, for example right after `const activeTab = ref<TabKey>(initialTab);`:

```typescript
const CHAT_COMPOSER_DISMISSED_KEY = "heym-dashboard-chat-composer-dismissed";

function readChatComposerDismissed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(CHAT_COMPOSER_DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

const chatComposerDismissed = ref(readChatComposerDismissed());

function dismissChatComposer(): void {
  chatComposerDismissed.value = true;
  try {
    window.localStorage.setItem(CHAT_COMPOSER_DISMISSED_KEY, "1");
  } catch {
    // Ignore storage failures; the composer still hides for this session.
  }
}

function restoreChatComposer(): void {
  chatComposerDismissed.value = false;
  try {
    window.localStorage.removeItem(CHAT_COMPOSER_DISMISSED_KEY);
  } catch {
    // Ignore storage failures; the composer still shows for this session.
  }
}

function openCredentialsTab(): void {
  activeTab.value = "credentials";
}
```

- [ ] **Step 3: Render the composer above the Workflows heading**

In the template, find this exact closing of the drag overlay `Transition` followed by the header row (around line 1471):

```html
            </Transition>

            <div class="relative z-10 flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-5">
```

Change it to:

```html
            </Transition>

            <DashboardChatComposer
              v-if="!chatComposerDismissed"
              @dismiss="dismissChatComposer"
              @open-credentials="openCredentialsTab"
            />

            <div class="relative z-10 flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-5">
```

- [ ] **Step 4: Add the `Ask AI` restore button**

Inside that same header row, the right-hand action group starts with:

```html
              <div class="flex flex-wrap items-center justify-end gap-1.5 sm:flex-nowrap">
```

Insert the restore button as its first child:

```html
              <div class="flex flex-wrap items-center justify-end gap-1.5 sm:flex-nowrap">
                <Button
                  v-if="chatComposerDismissed"
                  variant="ghost"
                  size="sm"
                  class="gap-1.5"
                  data-testid="dashboard-chat-composer-restore"
                  @click="restoreChatComposer"
                >
                  <Sparkles class="w-4 h-4" />
                  Ask AI
                </Button>
```

- [ ] **Step 5: Lint and typecheck**

Run from `frontend/`: `bun run lint && bun run typecheck`
Expected: both PASS.

- [ ] **Step 6: Manual verification**

With `./run.sh` running, open `http://localhost:4017/`:

1. The composer sits above the Workflows heading with `Welcome <your name>,` and preselected credential and model.
2. Type a prompt and press Enter. You land on `/chats/<id>`, your message is there, and the reply streams without a duplicate assistant bubble.
3. Go back to the dashboard. The composer is empty again.
4. Attach a `.txt`, `.png`, and `.pdf` in three separate sends. Each arrives with the file name on the user message.
5. Attach an unsupported file (for example `.zip`). The composer shows `Unsupported file type` and the send button stays disabled.
6. Switch to the Credentials tab and back. The composer does not appear on other tabs.
7. Click the `x`. The composer hides and `Ask AI` appears next to the heading. Reload the page: still hidden. Click `Ask AI`: it comes back and survives a reload.
8. Double click the send button quickly. Only one conversation is created.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/DashboardView.vue
git commit -m "feat: show chat composer on dashboard workflows tab"
```

---

### Task 5: Documentation and full check

**Files:**
- Modify: docs chosen by the `heym-documentation` skill (expect `frontend/src/docs/content/` pages covering the dashboard or the chat assistant)

- [ ] **Step 1: Update the docs**

Invoke the `heym-documentation` skill and ask it to document the dashboard chat composer: where it lives (Workflows tab), what it does (start an assistant chat with an optional file and a chosen credential and model), that submitting opens the conversation in the Chats tab, and that it can be hidden and restored with `Ask AI`. Keep the copy short and plain, no em dashes.

- [ ] **Step 2: Run the full check**

Run from the repo root:

```bash
SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh
```

Expected: frontend lint and typecheck PASS, backend Ruff PASS, backend tests PASS. `HEYM_OTEL_ENABLED=false` is required because a stale `.env` value plus no collector makes the suite hang.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: document the dashboard chat composer"
```

- [ ] **Step 4: Report, do not push**

Summarize what shipped and leave the commits local. Pushing requires explicit approval.
