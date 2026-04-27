<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Bot, Check, ChevronDown, Copy, Loader2, Mic, MicOff, Send, Square, Trash2 } from "lucide-vue-next";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { useRoute } from "vue-router";

import Button from "@/components/ui/Button.vue";
import ImageLightbox from "@/components/ui/ImageLightbox.vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import {
  consumeShowcaseChatDraft,
  SHOWCASE_CHAT_DRAFT_EVENT,
} from "@/features/showcase/showcaseChatDraft";
import { aiApi, credentialsApi, templatesApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import type { CredentialListItem, LLMModel } from "@/types/credential";
import type { NodeTemplate, WorkflowTemplate } from "@/features/templates/types/template.types";

const MAX_CONTEXT_MESSAGES = 25;

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  images?: string[];
}

interface SpeechRecognitionResultAlternative {
  transcript: string;
}

interface SpeechRecognitionResultItem {
  isFinal: boolean;
  0: SpeechRecognitionResultAlternative;
}

interface SpeechRecognitionResultList {
  length: number;
  [index: number]: SpeechRecognitionResultItem;
}

interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
}

interface SpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

interface SpeechRecognitionWindow extends Window {
  webkitSpeechRecognition?: new () => SpeechRecognition;
  SpeechRecognition?: new () => SpeechRecognition;
}

const allWorkflowTemplates = ref<WorkflowTemplate[]>([]);
const allNodeTemplates = ref<NodeTemplate[]>([]);

async function loadTemplatesForContext(): Promise<void> {
  try {
    const all = await templatesApi.list();
    allWorkflowTemplates.value = all.workflow_templates;
    allNodeTemplates.value = all.node_templates;
  } catch {
    allWorkflowTemplates.value = [];
    allNodeTemplates.value = [];
  }
}

function buildTemplateContext(): string {
  const wfLines = allWorkflowTemplates.value.map(
    (t) =>
      `- [Workflow Template] "${t.name}"${t.description ? `: ${t.description}` : ""}${t.tags.length ? ` (tags: ${t.tags.join(", ")})` : ""} (used ${t.use_count} times)`,
  );
  const nodeLines = allNodeTemplates.value.map(
    (t) =>
      `- [Node Template] "${t.name}" (type: ${t.node_type})${t.description ? `: ${t.description}` : ""}${t.tags.length ? ` (tags: ${t.tags.join(", ")})` : ""}`,
  );
  if (wfLines.length === 0 && nodeLines.length === 0) return "";
  return [
    "Available templates in this workspace:",
    ...wfLines,
    ...nodeLines,
  ].join("\n");
}

const credentials = ref<CredentialListItem[]>([]);
const selectedCredentialId = ref("");
const selectedModel = ref("");
const loadingModels = ref(false);
const modelsLoadFailed = ref(false);
const models = ref<LLMModel[]>([]);

const authStore = useAuthStore();
const messages = ref<ChatMessage[]>([]);
const inputText = ref("");
const streaming = ref(false);
const steps = ref<string[]>([]);
const messagesContainer = ref<HTMLElement | null>(null);
const chatInputRef = ref<HTMLTextAreaElement | null>(null);
const activeAbortController = ref<AbortController | null>(null);
const activeAssistantMessageId = ref<string | null>(null);

const speechRecognition = ref<SpeechRecognition | null>(null);
const isSpeechSupported = ref(false);
const isListening = ref(false);
const isFixingTranscription = ref(false);
const copiedMessageId = ref<string | null>(null);
let copiedMessageIdTimeout: ReturnType<typeof setTimeout> | null = null;

const imageLightboxSrc = ref<string | null>(null);
const route = useRoute();

function handleMarkdownImageClick(event: MouseEvent): void {
  const target = event.target as HTMLElement;
  if (target.tagName === "IMG") {
    const img = target as HTMLImageElement;
    imageLightboxSrc.value = img.src;
  }
}

const SM_BREAKPOINT = 640;
const isSmallScreen = ref(
  typeof window !== "undefined" && window.innerWidth < SM_BREAKPOINT,
);
function updateSmallScreen(): void {
  isSmallScreen.value = window.innerWidth < SM_BREAKPOINT;
}

const conversationHistoryForRequest = computed(() => {
  const relevant = messages.value.filter((m) => m.role === "user" || m.role === "assistant");
  const withoutLastTwo = relevant.slice(0, -2);
  const slice = withoutLastTwo.slice(-MAX_CONTEXT_MESSAGES);
  return slice.map((m) => ({ role: m.role, content: m.content }));
});

function pickDefaultModel(modelList: LLMModel[]): string {
  if (modelList.length === 0) return "";
  const lower = (s: string) => (s || "").toLowerCase();
  const isCerebrasGlm = (m: LLMModel) =>
    lower(m.name).includes("cerebras") ||
    lower(m.name).includes("glm") ||
    lower(m.name).includes("4.7") ||
    lower(m.id).includes("cerebras") ||
    lower(m.id).includes("glm") ||
    lower(m.id).includes("4.7");
  const cerebrasModels = modelList.filter(isCerebrasGlm);
  if (cerebrasModels.length > 0) {
    return cerebrasModels[cerebrasModels.length - 1].id;
  }
  return modelList[modelList.length - 1].id;
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
    modelsLoadFailed.value = false;
    selectedModel.value = "";
    return;
  }
  loadingModels.value = true;
  modelsLoadFailed.value = false;
  try {
    models.value = await credentialsApi.getModels(selectedCredentialId.value);
    if (models.value.length > 0) {
      selectedModel.value = pickDefaultModel(models.value);
    } else {
      selectedModel.value = "";
    }
  } catch {
    models.value = [];
    modelsLoadFailed.value = true;
    selectedModel.value = "";
  } finally {
    loadingModels.value = false;
  }
}

watch(selectedCredentialId, loadModels);

function setupSpeechRecognition(): void {
  const recognitionWindow = window as SpeechRecognitionWindow;
  const SpeechRecognitionConstructor =
    recognitionWindow.SpeechRecognition || recognitionWindow.webkitSpeechRecognition;
  if (!SpeechRecognitionConstructor) {
    isSpeechSupported.value = false;
    return;
  }
  isSpeechSupported.value = true;
  const recognition = new SpeechRecognitionConstructor();
  recognition.lang = "tr-TR";
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.onresult = (event: SpeechRecognitionEvent) => {
    const transcripts = Array.from(event.results).map((result) => result[0]?.transcript ?? "");
    const transcript = transcripts.join("").trim();
    if (transcript) {
      inputText.value = transcript;
    }
  };
  recognition.onerror = () => {
    isListening.value = false;
  };
  recognition.onend = () => {
    if (isListening.value && speechRecognition.value) {
      speechRecognition.value.start();
    } else {
      isListening.value = false;
    }
  };
  speechRecognition.value = recognition;
}

async function fixTranscriptionIfNeeded(): Promise<void> {
  const text = inputText.value.trim();
  if (!text || !selectedCredentialId.value || !selectedModel.value) return;

  isFixingTranscription.value = true;
  try {
    const response = await aiApi.fixTranscription({
      credentialId: selectedCredentialId.value,
      model: selectedModel.value,
      text: text,
    });
    inputText.value = response.fixed_text;
  } catch {
    // keep original text
  } finally {
    isFixingTranscription.value = false;
  }
}

function toggleSpeechInput(): void {
  if (!speechRecognition.value) return;
  if (isListening.value) {
    isListening.value = false;
    speechRecognition.value.stop();
    fixTranscriptionIfNeeded();
    return;
  }
  inputText.value = "";
  isListening.value = true;
  speechRecognition.value.start();
}

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
    if (streaming.value) {
      nextTick(scrollToBottomImmediate);
    }
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
      "video", "source",
    ],
    ALLOWED_ATTR: ["href", "target", "rel", "src", "alt", "controls", "playsinline", "muted", "loop", "preload", "type", "style"],
  });
}

function clearChat(): void {
  messages.value = [];
  nextTick(focusChatInput);
}

async function copyMessageContent(msg: ChatMessage): Promise<void> {
  const text = msg.content || "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copiedMessageId.value = msg.id;
    if (copiedMessageIdTimeout) clearTimeout(copiedMessageIdTimeout);
    copiedMessageIdTimeout = setTimeout(() => {
      copiedMessageId.value = null;
    }, 2000);
  } catch {
    // ignore clipboard errors
  }
}

function onBubbleClick(msg: ChatMessage): void {
  if (isSmallScreen.value) {
    copyMessageContent(msg);
  }
}

function handleSubmit(): void {
  const text = inputText.value.trim();
  if (
    !text
    || streaming.value
    || !selectedCredentialId.value
    || !selectedModel.value
    || modelsLoadFailed.value
  ) {
    return;
  }

  const userMsg: ChatMessage = {
    id: crypto.randomUUID(),
    role: "user",
    content: text,
  };
  messages.value.push(userMsg);
  inputText.value = "";

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

function stopStreaming(): void {
  if (!streaming.value) return;

  activeAbortController.value?.abort();
  streaming.value = false;
  steps.value = [];

  const assistantId = activeAssistantMessageId.value;
  if (assistantId) {
    const index = messages.value.findIndex((msg) => msg.id === assistantId);
    const message = index >= 0 ? messages.value[index] : null;
    if (
      message &&
      message.role === "assistant" &&
      !message.content.trim() &&
      (!message.images || message.images.length === 0)
    ) {
      messages.value.splice(index, 1);
    }
  }

  activeAbortController.value = null;
  activeAssistantMessageId.value = null;
  focusChatInput();
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    handleSubmit();
  }
}

function focusChatInput(): void {
  nextTick(() => {
    chatInputRef.value?.focus();
  });
}

function applyShowcaseDraft(): void {
  const draft = consumeShowcaseChatDraft();
  if (!draft) return;
  inputText.value = draft;
  focusChatInput();
}

onMounted(() => {
  setupSpeechRecognition();
  loadCredentials();
  loadTemplatesForContext();
  updateSmallScreen();
  window.addEventListener("resize", updateSmallScreen);
  window.addEventListener(SHOWCASE_CHAT_DRAFT_EVENT, applyShowcaseDraft);
  applyShowcaseDraft();
  focusChatInput();
});

const unsubDismissOverlays = onDismissOverlays(() => {
  imageLightboxSrc.value = null;
});

watch([selectedCredentialId, selectedModel], () => {
  if (selectedCredentialId.value && selectedModel.value) {
    focusChatInput();
  }
});

watch(
  () => route.fullPath,
  () => {
    applyShowcaseDraft();
  },
);

onUnmounted(() => {
  activeAbortController.value?.abort();
  unsubDismissOverlays();
  window.removeEventListener("resize", updateSmallScreen);
  window.removeEventListener(SHOWCASE_CHAT_DRAFT_EVENT, applyShowcaseDraft);
});
</script>

<template>
  <div class="dashboard-chat flex flex-col h-full w-full min-h-0 rounded-2xl border border-border/50 bg-card/60 backdrop-blur-md overflow-hidden">
    <!-- Header: stacked on mobile, row on desktop; touch-friendly -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 sm:gap-4 p-3 sm:p-4 border-b border-border/50">
      <div class="flex items-center gap-2 min-w-0 shrink-0">
        <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <Bot class="w-5 h-5 text-primary" />
        </div>
        <div class="min-w-0">
          <h2 class="text-base sm:text-lg font-semibold truncate">
            Chat
          </h2>
          <p class="text-xs sm:text-sm text-muted-foreground truncate">
            Run workflows and ask questions
          </p>
        </div>
      </div>
      <div class="flex flex-col sm:flex-row gap-2 sm:gap-2 sm:flex-nowrap sm:items-end">
        <div class="grid grid-cols-2 gap-2 sm:flex sm:items-end sm:gap-2 flex-1 min-w-0">
          <div class="chat-select-wrap relative flex flex-col min-w-0 sm:max-w-[140px]">
            <select
              v-model="selectedCredentialId"
              class="chat-select min-h-[44px] sm:min-h-0 sm:h-9 rounded-lg border border-input bg-background pl-3 pr-9 py-2.5 sm:py-0 text-sm touch-manipulation w-full truncate appearance-none cursor-pointer"
            >
              <option
                value=""
                disabled
              >
                Select...
              </option>
              <option
                v-for="c in credentials"
                :key="c.id"
                :value="c.id"
              >
                {{ c.name }}
              </option>
            </select>
            <ChevronDown class="chat-select-arrow pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground shrink-0" />
          </div>
          <div class="chat-select-wrap relative flex flex-col min-w-0 sm:max-w-[160px]">
            <select
              v-model="selectedModel"
              :disabled="!selectedCredentialId || loadingModels || modelsLoadFailed"
              class="chat-select min-h-[44px] sm:min-h-0 sm:h-9 rounded-lg border border-input bg-background pl-3 pr-9 py-2.5 sm:py-0 text-sm disabled:opacity-50 touch-manipulation w-full truncate appearance-none cursor-pointer"
            >
              <option
                value=""
                disabled
              >
                {{ loadingModels ? "Loading..." : modelsLoadFailed ? "Failed to load" : !selectedCredentialId ? "Select..." : "Select..." }}
              </option>
              <option
                v-for="m in models"
                :key="m.id"
                :value="m.id"
              >
                {{ m.name }}
              </option>
            </select>
            <ChevronDown class="chat-select-arrow pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground shrink-0" />
          </div>
        </div>
        <p
          v-if="modelsLoadFailed"
          class="text-xs text-amber-600 dark:text-amber-400 sm:max-w-[220px]"
        >
          This credential's model list could not be loaded. Chat stays disabled until a model can be fetched.
        </p>
        <Button
          v-if="messages.length > 0"
          variant="outline"
          size="sm"
          class="shrink-0 min-h-[44px] sm:min-h-0 w-full sm:w-auto"
          @click="clearChat"
        >
          <Trash2 class="w-4 h-4" />
          Clear
        </Button>
      </div>
    </div>

    <div
      ref="messagesContainer"
      :class="[
        'flex-1 min-h-0 p-3 sm:p-4 space-y-4 overflow-y-auto',
        messages.length === 0 && 'flex flex-col items-center justify-center',
      ]"
    >
      <div
        v-if="messages.length === 0"
        class="flex flex-col items-center justify-center text-center text-muted-foreground px-2 py-6 sm:py-8 gap-4"
      >
        <Send class="w-10 h-10 sm:w-12 sm:h-12 opacity-50" />
        <p class="text-xs sm:text-sm max-w-[280px] sm:max-w-none">
          Ask to run a workflow, list workflows, or ask about your data.
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
              'relative max-w-[85%] min-w-0 rounded-2xl px-3 py-2.5 sm:px-4 sm:py-3 pr-3 sm:pr-10 text-sm break-words',
              msg.role === 'user'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted/80 border border-border/50',
              'cursor-pointer sm:cursor-default',
            ]"
            :role="isSmallScreen ? 'button' : undefined"
            :aria-label="isSmallScreen ? 'Copy message' : undefined"
            @click="onBubbleClick(msg)"
          >
            <button
              type="button"
              class="absolute top-1.5 right-2 hidden sm:flex min-w-9 min-h-9 items-center justify-center rounded-lg touch-manipulation transition-colors hover:bg-black/10 dark:hover:bg-white/10 text-current opacity-70 hover:opacity-100"
              :title="copiedMessageId === msg.id ? 'Copied!' : 'Copy'"
              :aria-label="copiedMessageId === msg.id ? 'Copied' : 'Copy message'"
              @click.stop="copyMessageContent(msg)"
            >
              <Check
                v-if="copiedMessageId === msg.id"
                class="w-4 h-4 text-green-600 dark:text-green-400"
              />
              <Copy
                v-else
                class="w-4 h-4"
              />
            </button>
            <template v-if="msg.role === 'assistant'">
              <div
                v-if="steps.length > 0 && messages.at(-1)?.id === msg.id"
                class="mb-3 space-y-1.5"
              >
                <div
                  v-for="(step, idx) in steps"
                  :key="idx"
                  class="flex items-center gap-2 text-xs text-muted-foreground"
                >
                  <Loader2
                    v-if="streaming && idx === steps.length - 1"
                    class="w-3.5 h-3.5 shrink-0 animate-spin"
                  />
                  <span
                    v-else
                    class="shrink-0 size-3.5 rounded-full bg-primary/20 flex items-center justify-center"
                  >
                    <span class="text-[10px] text-primary">✓</span>
                  </span>
                  <span>{{ step }}</span>
                </div>
              </div>
              <!-- eslint-disable vue/no-v-html -->
              <div
                v-if="msg.content"
                class="markdown-content break-words overflow-wrap-anywhere prose prose-sm dark:prose-invert max-w-none"
                @click="handleMarkdownImageClick"
                v-html="renderMarkdown(msg.content)"
              />
              <!-- eslint-enable vue/no-v-html -->
              <div
                v-if="msg.images && msg.images.length > 0"
                class="mt-2 flex flex-wrap gap-2"
              >
                <img
                  v-for="(imgSrc, idx) in msg.images"
                  :key="idx"
                  :src="imgSrc"
                  alt="Generated image"
                  class="max-h-48 max-w-full rounded-lg object-contain cursor-zoom-in border border-border/30 hover:border-border/60 transition-colors"
                  @click.stop="imageLightboxSrc = imgSrc"
                >
              </div>
              <div
                v-else-if="streaming"
                class="flex items-center gap-2 text-muted-foreground"
              >
                <Loader2 class="w-4 h-4 animate-spin shrink-0" />
                <span>{{ steps.length > 0 ? "Preparing response..." : "Thinking..." }}</span>
              </div>
            </template>
            <p
              v-else
              class="whitespace-pre-wrap break-words overflow-wrap-anywhere"
            >
              {{ msg.content }}
            </p>
          </div>
        </div>
      </template>
    </div>

    <ImageLightbox
      :src="imageLightboxSrc"
      alt="Generated image"
      @close="imageLightboxSrc = null"
    />

    <div class="chat-input-area shrink-0 px-3 sm:px-4 pt-3 sm:pt-4 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <form
        class="flex items-center gap-2 rounded-2xl bg-muted/40 border border-border/40 px-3 py-2 min-h-[52px] focus-within:border-primary/30 focus-within:bg-muted/50 transition-colors"
        @submit.prevent="handleSubmit"
      >
        <textarea
          ref="chatInputRef"
          v-model="inputText"
          :disabled="streaming || !selectedCredentialId || !selectedModel || modelsLoadFailed"
          placeholder="Type a message..."
          rows="1"
          class="chat-input flex-1 min-h-[44px] max-h-40 resize-none bg-transparent border-0 px-1 py-3 text-sm text-left focus:outline-none focus:ring-0 disabled:opacity-50 touch-manipulation placeholder:text-muted-foreground leading-5"
          @keydown="handleKeydown"
        />
        <button
          v-if="isSpeechSupported"
          type="button"
          class="shrink-0 h-9 w-9 min-h-[36px] min-w-[36px] rounded-xl flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/80 disabled:opacity-50 disabled:pointer-events-none touch-manipulation transition-colors"
          :disabled="streaming || isFixingTranscription || !selectedCredentialId || !selectedModel || modelsLoadFailed"
          :title="isListening ? 'Stop voice input' : isFixingTranscription ? 'Fixing...' : 'Voice input'"
          @click="toggleSpeechInput"
        >
          <Loader2
            v-if="isFixingTranscription"
            class="w-4 h-4 animate-spin"
          />
          <component
            :is="isListening ? MicOff : Mic"
            v-else
            class="w-4 h-4"
          />
        </button>
        <Button
          v-if="!streaming"
          type="submit"
          variant="gradient"
          size="icon"
          :disabled="!inputText.trim() || !selectedCredentialId || !selectedModel || modelsLoadFailed"
          class="shrink-0 h-9 w-9 min-h-[36px] min-w-[36px] rounded-xl touch-manipulation"
        >
          <Send class="w-4 h-4" />
        </Button>
        <Button
          v-else
          type="button"
          variant="destructive"
          size="icon"
          class="shrink-0 h-9 w-9 min-h-[36px] min-w-[36px] rounded-xl touch-manipulation"
          @click="stopStreaming"
        >
          <Square class="w-4 h-4" />
        </Button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4),
.markdown-content :deep(h5),
.markdown-content :deep(h6) {
  font-weight: 600;
  margin-top: 1em;
  margin-bottom: 0.5em;
}
.markdown-content :deep(p) {
  margin-top: 0.5em;
  margin-bottom: 0.5em;
}
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin-top: 0.5em;
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
  margin-top: 0.75em;
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
.markdown-content :deep(img) {
  max-width: 100%;
  max-height: 16rem;
  border-radius: 0.5rem;
  cursor: zoom-in;
  margin-top: 0.5em;
  margin-bottom: 0.5em;
}
</style>
