<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
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
const MAX_INPUT_HEIGHT_PX = 180;
const PLACEHOLDER_ROTATION_MS = 5000;
const PROMPT_SUGGESTIONS: string[] = [
  "Ask anything, or describe a workflow to build",
  "Run my daily report workflow",
  "Which scheduled workflows run this week?",
  "Add a task to my Kanban board",
  "What is stored in my global variables?",
  "Which workflow templates are available?",
  // Titles from the beginner templates collection on heym.run.
  "Daily sales snapshot to Slack",
  "Save Slack requests to Google Sheets",
  "New leads sheet to Slack",
  "Log Slack messages in BigQuery",
  "BigQuery report to Google Sheets",
  "Google Sheets to BigQuery sync",
  "Save Slack feedback and notify product",
  "Daily low-stock alert to Slack",
  "Weekly cloud spend to Google Sheets",
  "Log Slack partner leads in BigQuery",
  "Daily Google Sheets lead digest by email",
  "Email new Slack feedback",
];

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
const placeholderIndex = ref(0);
const isInputFocused = ref(false);
const isDraggingFile = ref(false);
let placeholderTimer: ReturnType<typeof setInterval> | null = null;
let dragCounter = 0;

const currentPlaceholder = computed<string>(
  () => PROMPT_SUGGESTIONS[placeholderIndex.value] ?? PROMPT_SUGGESTIONS[0],
);

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

function dragCarriesFiles(event: DragEvent): boolean {
  return Boolean(event.dataTransfer?.types.includes("Files"));
}

function onDragEnter(event: DragEvent): void {
  if (!dragCarriesFiles(event)) return;
  event.preventDefault();
  dragCounter += 1;
  isDraggingFile.value = true;
}

function onDragOver(event: DragEvent): void {
  if (!dragCarriesFiles(event)) return;
  event.preventDefault();
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = "copy";
  }
  isDraggingFile.value = true;
}

function onDragLeave(): void {
  dragCounter -= 1;
  if (dragCounter <= 0) {
    dragCounter = 0;
    isDraggingFile.value = false;
  }
}

/** Stops propagation so the Workflows tab does not import the file as a workflow. */
async function onDrop(event: DragEvent): Promise<void> {
  event.preventDefault();
  event.stopPropagation();
  dragCounter = 0;
  isDraggingFile.value = false;
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  await processFile(file);
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
  placeholderTimer = setInterval(() => {
    // Hold still while the box is in use, so the line never moves under the
    // caret and never jumps when a draft is cleared.
    if (input.value.length > 0 || isInputFocused.value) return;
    placeholderIndex.value = (placeholderIndex.value + 1) % PROMPT_SUGGESTIONS.length;
  }, PLACEHOLDER_ROTATION_MS);
});

onUnmounted(() => {
  if (placeholderTimer) {
    clearInterval(placeholderTimer);
    placeholderTimer = null;
  }
});
</script>

<template>
  <section
    data-testid="dashboard-chat-composer"
    class="relative z-10 mb-5 rounded-2xl border border-border/50 bg-card/60 px-4 pb-5 pt-3.5 shadow-sm sm:px-6 sm:pb-6 sm:pt-4"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <div
      v-if="isDraggingFile"
      class="pointer-events-none absolute inset-0 z-30 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-background/85"
    >
      <div class="flex items-center gap-2 text-sm font-medium text-primary">
        <Paperclip class="h-4 w-4" />
        Drop file to attach
      </div>
    </div>

    <button
      type="button"
      class="absolute right-6 top-3.5 flex h-9 w-9 items-center justify-center rounded-lg border border-border/60 bg-background/70 text-foreground/70 transition-colors hover:border-border hover:bg-muted hover:text-foreground"
      aria-label="Hide chat box"
      title="Hide"
      @click="emit('dismiss')"
    >
      <X class="h-5 w-5" />
    </button>

    <div class="pr-16">
      <h2 class="text-lg font-bold tracking-tight sm:text-xl">
        {{ greeting }}
      </h2>
      <p class="mt-0.5 text-sm text-muted-foreground">
        What do you want to automate?
      </p>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      :accept="ATTACHMENT_ACCEPT"
      class="hidden"
      @change="handleFileInputChange"
    >

    <form
      class="mt-4 rounded-2xl border border-border/40 bg-muted/40 px-2.5 pb-2.5 pt-4 transition-colors focus-within:border-primary/30 focus-within:bg-muted/50 sm:px-3.5 sm:pb-3 sm:pt-4"
      @submit.prevent="submit"
    >
      <div class="relative">
        <textarea
          ref="inputRef"
          v-model="input"
          rows="1"
          data-testid="dashboard-chat-input"
          aria-label="Message"
          class="min-h-[24px] w-full resize-none bg-transparent px-2.5 py-0 text-[15px] leading-6 text-foreground outline-none sm:text-base"
          @input="onInput"
          @keydown="onKeydown"
          @focus="isInputFocused = true"
          @blur="isInputFocused = false"
        />

        <Transition
          name="composer-placeholder"
          mode="out-in"
        >
          <p
            v-if="!input"
            :key="placeholderIndex"
            class="pointer-events-none absolute left-2.5 right-2.5 top-0 truncate text-[15px] leading-6 text-muted-foreground sm:text-base"
          >
            {{ currentPlaceholder }}
          </p>
        </Transition>
      </div>

      <div class="mt-0 flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2">
        <div class="order-2 flex items-center justify-between gap-2 sm:contents">
          <button
            type="button"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground disabled:pointer-events-none disabled:opacity-50 sm:order-1"
            :disabled="attachmentLoading"
            title="Attach file"
            aria-label="Attach file"
            @click="openFilePicker"
          >
            <Paperclip class="h-4 w-4" />
          </button>

          <button
            type="submit"
            data-testid="dashboard-chat-send"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50 sm:order-3 sm:ml-1"
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

        <div class="order-1 flex w-full max-w-full flex-wrap items-center justify-between gap-1 sm:order-2 sm:ml-auto sm:w-auto sm:flex-nowrap sm:justify-end">
          <div
            class="max-w-full shrink-0"
            data-testid="dashboard-chat-credential-selector"
          >
            <SearchableSelect
              id="dashboard-chat-credential-select"
              :model-value="selectedCredentialId"
              :options="credentialOptions"
              placeholder="Credential"
              search-placeholder="Search credentials..."
              empty-text="No credentials found."
              :disabled="!hasCredentials"
              hide-trigger-icon
              select-class="h-8 min-h-0 rounded-lg border-transparent bg-transparent text-muted-foreground shadow-none hover:border-transparent hover:bg-muted/70 focus-within:border-transparent focus-within:ring-0"
              content-class="z-[60]"
              @update:model-value="onCredentialSelect"
            />
          </div>

          <div
            class="max-w-full shrink-0"
            data-testid="dashboard-chat-model-selector"
          >
            <SearchableSelect
              id="dashboard-chat-model-select"
              :model-value="selectedModel"
              :options="modelOptions"
              :placeholder="isLoadingModels || modelsLoadFailed ? modelPlaceholder : 'Model'"
              search-placeholder="Search models..."
              empty-text="No models found."
              :disabled="!selectedCredentialId || isLoadingModels || modelsLoadFailed"
              hide-trigger-icon
              select-class="h-8 min-h-0 rounded-lg border-transparent bg-transparent text-muted-foreground shadow-none hover:border-transparent hover:bg-muted/70 focus-within:border-transparent focus-within:ring-0"
              content-class="z-[60]"
              @update:model-value="selectedModel = $event ?? ''"
            />
          </div>
        </div>
      </div>
      <div
        v-if="attachedFile || attachmentError || modelsLoadFailed || showNoCredentialsHint || submitError"
        class="mt-2 flex flex-wrap items-center gap-2 px-1"
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
    </form>
  </section>
</template>

<style scoped>
.composer-placeholder-enter-active,
.composer-placeholder-leave-active {
  transition:
    transform 420ms cubic-bezier(0.22, 1, 0.36, 1),
    opacity 320ms ease;
}

.composer-placeholder-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.composer-placeholder-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

@media (prefers-reduced-motion: reduce) {
  .composer-placeholder-enter-active,
  .composer-placeholder-leave-active {
    transition: opacity 120ms ease;
  }

  .composer-placeholder-enter-from,
  .composer-placeholder-leave-to {
    transform: none;
  }
}
</style>
