<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useMediaQuery } from "@vueuse/core";
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

const isNarrowViewport = useMediaQuery("(max-width: 639px)");

// The long prompt wraps and clips inside the one-line box on small screens.
const inputPlaceholder = computed<string>(() =>
  isNarrowViewport.value ? "Ask anything" : "Ask anything, or describe a workflow to build",
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
    class="relative z-10 mb-5 rounded-2xl border border-border/50 bg-card/60 px-4 py-5 shadow-sm sm:px-6 sm:py-6"
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

    <div class="flex flex-col gap-3 pr-8 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div class="min-w-0">
        <h2 class="text-lg font-bold tracking-tight sm:text-xl">
          {{ greeting }}
        </h2>
        <p class="mt-0.5 text-sm text-muted-foreground">
          What do you want to automate?
        </p>
      </div>

      <div class="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:shrink-0">
        <div
          class="min-w-0 sm:max-w-[240px]"
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
            select-class="h-8 rounded-lg border-input bg-background shadow-none"
            content-class="z-[60]"
            @update:model-value="onCredentialSelect"
          />
        </div>

        <div
          class="min-w-0 sm:max-w-[240px]"
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
            select-class="h-8 rounded-lg border-input bg-background shadow-none"
            content-class="z-[60]"
            @update:model-value="selectedModel = $event ?? ''"
          />
        </div>
      </div>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      :accept="ATTACHMENT_ACCEPT"
      class="hidden"
      @change="handleFileInputChange"
    >

    <form
      class="mt-4 flex items-start gap-2 rounded-2xl border border-border/40 bg-muted/40 px-2.5 py-2.5 transition-colors focus-within:border-primary/30 focus-within:bg-muted/50 sm:gap-2.5 sm:px-3.5 sm:py-3"
      @submit.prevent="submit"
    >
      <button
        type="button"
        class="flex h-11 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground sm:h-[52px] sm:w-10 transition-colors hover:bg-muted/80 hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
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
        :placeholder="inputPlaceholder"
        class="min-h-[44px] w-full flex-1 resize-none bg-transparent px-1.5 py-2 text-sm leading-7 sm:min-h-[52px] sm:px-2 sm:py-3 text-foreground outline-none placeholder:text-muted-foreground sm:text-[15px]"
        @input="onInput"
        @keydown="onKeydown"
      />

      <div class="flex h-11 shrink-0 items-center sm:h-[52px]">
        <button
          type="submit"
          data-testid="dashboard-chat-send"
          class="flex h-9 w-9 items-center justify-center rounded-xl bg-primary sm:h-10 sm:w-10 text-primary-foreground transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
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
