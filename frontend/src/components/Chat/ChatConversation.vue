<script setup lang="ts">
import { ref, watch, nextTick, onMounted, computed, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import {
  Send,
  Bot,
  Loader2,
  ChevronRight,
  ChevronDown,
  Copy,
  Check,
  ExternalLink,
  Square,
  Mic,
  MicOff,
  Paperclip,
  Pencil,
  TriangleAlert,
  Volume2,
  AudioLines,
  X,
} from "lucide-vue-next";
import { marked } from "marked";
import DOMPurify from "dompurify";

import type { Message, WorkflowPreview } from "@/types/chat";
import type { CredentialListItem, LLMModel } from "@/types/credential";
import ChatToolCall from "@/components/Chat/ChatToolCall.vue";
import ChatContextBadge from "@/components/Chat/ChatContextBadge.vue";
import ReadonlyCanvasPreview from "@/components/Canvas/ReadonlyCanvasPreview.vue";
import Button from "@/components/ui/Button.vue";
import ImageLightbox from "@/components/ui/ImageLightbox.vue";
import { estimateTokens } from "@/lib/contextEstimator";
import { aiApi, credentialsApi } from "@/services/api";
import { useFileAttachment } from "@/composables/useFileAttachment";
import type { AttachedFile } from "@/composables/useFileAttachment";
import { useQuickPrompts } from "@/composables/useQuickPrompts";
import {
  consumeShowcaseChatDraft,
  SHOWCASE_CHAT_DRAFT_EVENT,
} from "@/features/showcase/showcaseChatDraft";
import { useAuthStore } from "@/stores/auth";
import { useChatStore } from "@/stores/chat";
import { useVoiceStore } from "@/stores/voice";
import { useTextToSpeech } from "@/composables/useTextToSpeech";
import InteractiveVoiceMode from "@/components/Chat/InteractiveVoiceMode.vue";

interface Props {
  conversationId: string;
}

const props = defineProps<Props>();

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CHAT_SCROLLBAR_VERTICAL_INSET_PX = 12;

const chatStore = useChatStore();
const authStore = useAuthStore();
const router = useRouter();

const input = ref("");
const chatRootRef = ref<HTMLDivElement | null>(null);
const chatInputRef = ref<HTMLTextAreaElement | null>(null);
const messagesScrollRef = ref<HTMLDivElement | null>(null);
const chatScrollbarTrackRef = ref<HTMLDivElement | null>(null);
const messagesEndRef = ref<HTMLElement | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const credentials = ref<CredentialListItem[]>([]);
const models = ref<LLMModel[]>([]);
const selectedCredentialId = ref("");
const selectedModel = ref("");
const isLoadingModels = ref(false);
const credentialError = ref("");
const modelsLoadFailed = ref(false);
const copiedMessageId = ref<string | null>(null);
const speechRecognition = ref<SpeechRecognition | null>(null);
const isSpeechSupported = ref(false);
const isListening = ref(false);
const isFixingTranscription = ref(false);
const imageLightboxSrc = ref<string | null>(null);
const selectedWorkflowPreviewNodes = ref<Record<string, Record<string, unknown> | null>>({});
const chatScrollbarThumbTop = ref(0);
const chatScrollbarThumbHeight = ref(44);
const isDraggingChatScrollbar = ref(false);
let copiedMessageIdTimeout: ReturnType<typeof setTimeout> | null = null;
let messagesResizeObserver: ResizeObserver | null = null;
let chatScrollbarDragStartY = 0;
let chatScrollbarDragStartScrollTop = 0;

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

const { attachedFile, attachmentError, attachmentLoading, processFile, clearAttachment } =
  useFileAttachment();
const { editingIndex: qpEditingIndex, editingValue: qpEditingValue, startEdit: qpStartEdit, commitEdit: qpCommitEdit, onEditKeydown: qpOnEditKeydown } =
  useQuickPrompts();

const isDraggingFile = ref(false);
let dragCounter = 0;

function handleDragEnter(event: DragEvent): void {
  if (!event.dataTransfer?.types.includes("Files")) return;
  event.preventDefault();
  dragCounter++;
  isDraggingFile.value = true;
}

function handleDragOver(event: DragEvent): void {
  if (!event.dataTransfer?.types.includes("Files")) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
}

function handleDragLeave(): void {
  dragCounter--;
  if (dragCounter <= 0) {
    dragCounter = 0;
    isDraggingFile.value = false;
  }
}

function handleDrop(event: DragEvent): void {
  event.preventDefault();
  dragCounter = 0;
  isDraggingFile.value = false;
  const file = event.dataTransfer?.files[0];
  if (file) {
    void processFile(file);
  }
}

const isShowingConversation = computed(
  () => chatStore.activeConversation?.id === props.conversationId,
);
const isTitleLoading = computed(() => !isShowingConversation.value);
const isConversationTransitioning = computed(
  () => chatStore.activeConversation !== null && !isShowingConversation.value,
);
const messages = computed(() => chatStore.activeConversation?.messages ?? []);
const conversationTitle = computed(() =>
  chatStore.activeConversation?.title ?? "",
);
const canSendMessage = computed(() => isShowingConversation.value && !isConversationTransitioning.value);
const streamState = computed(() => chatStore.getStreamState(props.conversationId));
const isThisConvStreaming = computed(() => streamState.value.isStreaming);
const draftTokens = computed(() => estimateTokens(input.value));
const contextUsageForBadge = computed(() => {
  const live = streamState.value.contextUsage;
  if (live) return live;
  return chatStore.contextUsageByConv[props.conversationId] ?? null;
});
const canFocusInput = computed(
  () =>
    canSendMessage.value &&
    !isThisConvStreaming.value &&
    !isLoadingModels.value &&
    !modelsLoadFailed.value &&
    Boolean(selectedCredentialId.value) &&
    Boolean(selectedModel.value),
);
const userInitial = computed(() => {
  const source = authStore.user?.name?.trim() || authStore.user?.email?.trim() || "?";
  return source.charAt(0).toUpperCase();
});
const chatScrollbarThumbStyle = computed(() => ({
  height: `${chatScrollbarThumbHeight.value}px`,
  transform: `translateY(${chatScrollbarThumbTop.value}px)`,
}));
const chatScrollbarAriaValueNow = computed(() => {
  const trackHeight = chatScrollbarTrackRef.value?.clientHeight ?? 0;
  const maxThumbTop = Math.max(trackHeight - chatScrollbarThumbHeight.value, 0);
  if (maxThumbTop <= 0) return 0;
  return Math.round((chatScrollbarThumbTop.value / maxThumbTop) * 100);
});

watch(
  () => props.conversationId,
  (id) => {
    void loadConversationForRoute(id);
    applyShowcaseDraft();
    focusInputWhenReady();
  },
);

watch(messages, () => {
  nextTick(() => {
    scrollToBottom();
    updateMessageScrollbar();
  });
});

watch(
  () => streamState.value.content,
  () => {
    if (!isThisConvStreaming.value) return;
    nextTick(() => {
      scrollToBottom();
      updateMessageScrollbar();
    });
  },
);

watch(
  () => streamState.value.error,
  () => {
    nextTick(() => {
      scrollToBottom();
      updateMessageScrollbar();
    });
  },
);

watch(qpEditingIndex, (index) => {
  if (index === null) return;
  nextTick(() => {
    (chatRootRef.value?.querySelector("[data-qp-edit]") as HTMLInputElement | null)?.focus();
  });
});

watch(
  canFocusInput,
  (canFocus) => {
    if (canFocus) {
      focusInputWhenReady();
    }
  },
);

watch(
  () => chatStore.activeConversation?.id,
  () => {
    focusInputWhenReady();
  },
);

watch(selectedModel, () => {
  void _maybeLoadContextSummary();
});

function scrollToBottom(): void {
  messagesEndRef.value?.scrollIntoView({ behavior: "smooth" });
}

function updateMessageScrollbar(): void {
  const scrollElement = messagesScrollRef.value;
  if (!scrollElement) return;

  const metrics = getMessageScrollbarMetrics();
  if (!metrics) return;

  const rawThumbHeight = metrics.maxScrollTop > 0
    ? (metrics.viewportHeight / scrollElement.scrollHeight) * metrics.trackHeight
    : metrics.trackHeight;
  const thumbHeight = metrics.trackHeight > 0
    ? Math.max(44, Math.min(metrics.trackHeight, rawThumbHeight))
    : 0;
  const maxThumbTop = Math.max(metrics.trackHeight - thumbHeight, 0);
  const thumbTop = metrics.maxScrollTop > 0
    ? (scrollElement.scrollTop / metrics.maxScrollTop) * maxThumbTop
    : 0;

  chatScrollbarThumbHeight.value = Math.round(thumbHeight);
  chatScrollbarThumbTop.value = Math.round(thumbTop);
}

function getMessageScrollbarMetrics(): {
  maxScrollTop: number;
  trackHeight: number;
  viewportHeight: number;
} | null {
  const scrollElement = messagesScrollRef.value;
  if (!scrollElement) return null;

  const viewportHeight = scrollElement.clientHeight;
  const trackHeight = chatScrollbarTrackRef.value?.clientHeight
    ?? Math.max(viewportHeight - CHAT_SCROLLBAR_VERTICAL_INSET_PX * 2, 0);
  return {
    maxScrollTop: Math.max(scrollElement.scrollHeight - viewportHeight, 0),
    trackHeight,
    viewportHeight,
  };
}

function scrollMessagesFromThumbTop(thumbTop: number): void {
  const scrollElement = messagesScrollRef.value;
  const metrics = getMessageScrollbarMetrics();
  if (!scrollElement || !metrics) return;

  const maxThumbTop = Math.max(metrics.trackHeight - chatScrollbarThumbHeight.value, 0);
  const clampedThumbTop = Math.min(Math.max(thumbTop, 0), maxThumbTop);
  scrollElement.scrollTop = maxThumbTop > 0
    ? (clampedThumbTop / maxThumbTop) * metrics.maxScrollTop
    : 0;
  updateMessageScrollbar();
}

function handleChatScrollbarTrackPointerDown(event: PointerEvent): void {
  const trackElement = chatScrollbarTrackRef.value;
  if (!trackElement) return;
  event.preventDefault();
  const trackTop = trackElement.getBoundingClientRect().top;
  const targetThumbTop = event.clientY - trackTop - chatScrollbarThumbHeight.value / 2;
  scrollMessagesFromThumbTop(targetThumbTop);
}

function handleChatScrollbarThumbPointerDown(event: PointerEvent): void {
  event.preventDefault();
  isDraggingChatScrollbar.value = true;
  chatScrollbarDragStartY = event.clientY;
  chatScrollbarDragStartScrollTop = messagesScrollRef.value?.scrollTop ?? 0;
  window.addEventListener("pointermove", handleChatScrollbarPointerMove);
  window.addEventListener("pointerup", handleChatScrollbarPointerUp);
}

function handleChatScrollbarPointerMove(event: PointerEvent): void {
  if (!isDraggingChatScrollbar.value) return;
  event.preventDefault();
  const scrollElement = messagesScrollRef.value;
  const metrics = getMessageScrollbarMetrics();
  if (!scrollElement || !metrics) return;

  const maxThumbTop = Math.max(metrics.trackHeight - chatScrollbarThumbHeight.value, 0);
  if (maxThumbTop <= 0) return;
  const deltaY = event.clientY - chatScrollbarDragStartY;
  scrollElement.scrollTop = chatScrollbarDragStartScrollTop
    + (deltaY / maxThumbTop) * metrics.maxScrollTop;
  updateMessageScrollbar();
}

function handleChatScrollbarPointerUp(): void {
  isDraggingChatScrollbar.value = false;
  window.removeEventListener("pointermove", handleChatScrollbarPointerMove);
  window.removeEventListener("pointerup", handleChatScrollbarPointerUp);
}

function focusInputWhenReady(): void {
  nextTick(() => {
    if (canFocusInput.value) {
      chatInputRef.value?.focus();
    }
  });
}

function resizeChatInput(): void {
  const textarea = chatInputRef.value;
  if (!textarea) return;
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function resetChatInputHeight(): void {
  nextTick(() => {
    const textarea = chatInputRef.value;
    if (!textarea) return;
    textarea.style.height = "auto";
  });
}

function applyShowcaseDraft(): void {
  const draft = consumeShowcaseChatDraft();
  if (!draft) return;
  input.value = draft;
  nextTick(resizeChatInput);
  focusInputWhenReady();
}

let _credentialsReady = false;

async function loadConversationForRoute(id: string): Promise<void> {
  if (!UUID_PATTERN.test(id)) {
    await router.replace("/chats");
    return;
  }

  const result = await chatStore.loadConversation(id);
  if (result === "not_found" && props.conversationId === id) {
    await router.replace("/chats");
    return;
  }
  if (result === "loaded" && _credentialsReady) {
    _applyConversationSession();
  }
}

onMounted(() => {
  setupSpeechRecognition();
  void loadConversationForRoute(props.conversationId);
  void loadCredentials();
  void chatStore.loadQuickPrompts();
  window.addEventListener(SHOWCASE_CHAT_DRAFT_EVENT, applyShowcaseDraft);
  window.addEventListener("resize", updateMessageScrollbar);
  if (typeof ResizeObserver !== "undefined" && messagesScrollRef.value) {
    messagesResizeObserver = new ResizeObserver(updateMessageScrollbar);
    messagesResizeObserver.observe(messagesScrollRef.value);
  }
  applyShowcaseDraft();
  focusInputWhenReady();
  nextTick(updateMessageScrollbar);
});

function renderMarkdown(content: string): string {
  if (!content) return "";
  const html = marked(content, { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      "p", "br", "strong", "em", "u", "s", "code", "pre", "blockquote",
      "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "hr",
      "table", "thead", "tbody", "tr", "th", "td", "img", "video", "source",
    ],
    ALLOWED_ATTR: [
      "href", "target", "rel", "src", "alt", "controls", "playsinline",
      "muted", "loop", "preload", "type", "style",
    ],
  });
}

function handleMarkdownImageClick(event: MouseEvent): void {
  const target = event.target as HTMLElement;
  if (target.tagName === "IMG") {
    imageLightboxSrc.value = (target as HTMLImageElement).src;
  }
}

function setWorkflowPreviewSelection(
  workflowId: string,
  node: Record<string, unknown> | null,
): void {
  selectedWorkflowPreviewNodes.value = {
    ...selectedWorkflowPreviewNodes.value,
    [workflowId]: node,
  };
  if (node) {
    nextTick(() => {
      chatRootRef.value?.focus({ preventScroll: true });
    });
  }
}

function hasWorkflowPreviewSelection(workflow: WorkflowPreview): boolean {
  return !!selectedWorkflowPreviewNodes.value[workflow.id];
}

function hasOpenWorkflowPreviewPanel(): boolean {
  return Object.values(selectedWorkflowPreviewNodes.value).some(Boolean);
}

function closeWorkflowPreviewPanels(): void {
  selectedWorkflowPreviewNodes.value = {};
}

function handleChatKeydown(event: KeyboardEvent): void {
  if (!["Escape", "Esc"].includes(event.key)) return;
  if (!hasOpenWorkflowPreviewPanel()) return;
  event.preventDefault();
  event.stopPropagation();
  closeWorkflowPreviewPanels();
}

async function copyMessage(msg: Message): Promise<void> {
  if (!msg.content) return;
  try {
    await navigator.clipboard.writeText(msg.content);
    copiedMessageId.value = msg.id;
    if (copiedMessageIdTimeout) clearTimeout(copiedMessageIdTimeout);
    copiedMessageIdTimeout = setTimeout(() => {
      copiedMessageId.value = null;
    }, 1600);
  } catch {
    // ignore clipboard errors
  }
}

const tts = useTextToSpeech();
const voiceStore = useVoiceStore();

function plainTextFromMarkdown(markdown: string): string {
  const div = document.createElement("div");
  div.innerHTML = renderMarkdown(markdown);
  return (div.textContent || div.innerText || "").trim();
}

async function readMessageAloud(msg: Message): Promise<void> {
  if (!tts.isConfigured.value) {
    voiceStore.requestVoiceSettings();
    return;
  }
  try {
    await tts.speak(msg.id, plainTextFromMarkdown(msg.content));
  } catch {
    // playback/synthesis failure is non-fatal; reset playback state
    tts.stop();
  }
}

const interactiveVoiceOpen = ref(false);

function openInteractiveVoice(): void {
  if (!tts.isConfigured.value) {
    voiceStore.requestVoiceSettings();
    return;
  }
  interactiveVoiceOpen.value = true;
}

async function sendVoiceText(text: string): Promise<void> {
  if (!selectedCredentialId.value || !selectedModel.value) return;
  await chatStore.sendMessage(
    props.conversationId,
    text,
    selectedCredentialId.value,
    selectedModel.value,
  );
}

function openFilePicker(): void {
  fileInputRef.value?.click();
}

async function handleFileInputChange(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  await processFile(file);
  target.value = "";
}

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
      input.value = transcript;
      nextTick(resizeChatInput);
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
  const text = input.value.trim();
  if (!text || !selectedCredentialId.value || !selectedModel.value) return;

  isFixingTranscription.value = true;
  try {
    const response = await aiApi.fixTranscription({
      credentialId: selectedCredentialId.value,
      model: selectedModel.value,
      text,
    });
    input.value = response.fixed_text;
    nextTick(resizeChatInput);
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
  input.value = "";
  isListening.value = true;
  speechRecognition.value.start();
}

function _applyConversationSession(): void {
  const conv = chatStore.activeConversation;
  if (!conv || !credentials.value.length) return;
  const savedCredId = conv.last_credential_id;
  const savedModel = conv.last_model;
  if (savedCredId) {
    const credMatch = credentials.value.find((c) => c.id === savedCredId);
    if (credMatch) {
      selectedCredentialId.value = credMatch.id;
      void loadModels(credMatch.id, savedModel ?? undefined);
      return;
    }
  }
  if (!selectedCredentialId.value) {
    selectedCredentialId.value = credentials.value[0].id;
    void loadModels(credentials.value[0].id);
  }
}

async function loadCredentials(): Promise<void> {
  try {
    credentials.value = await credentialsApi.listLLM();
    _credentialsReady = true;
    if (credentials.value.length > 0) {
      if (chatStore.activeConversation) {
        _applyConversationSession();
      } else if (!selectedCredentialId.value) {
        selectedCredentialId.value = credentials.value[0].id;
        await loadModels(credentials.value[0].id);
      }
    }
  } catch {
    credentialError.value = "Failed to load credentials";
  }
}

async function loadModels(credId: string, preferredModelId?: string): Promise<void> {
  if (!credId) return;
  isLoadingModels.value = true;
  modelsLoadFailed.value = false;
  models.value = [];
  selectedModel.value = "";
  try {
    models.value = await credentialsApi.getModels(credId);
    if (models.value.length > 0) {
      const match = preferredModelId
        ? models.value.find((m) => m.id === preferredModelId)
        : null;
      selectedModel.value = match ? match.id : models.value[models.value.length - 1].id;
    }
  } catch {
    modelsLoadFailed.value = true;
  } finally {
    isLoadingModels.value = false;
    focusInputWhenReady();
    void _maybeLoadContextSummary();
  }
}

async function _maybeLoadContextSummary(): Promise<void> {
  if (!selectedCredentialId.value || !selectedModel.value) return;
  await chatStore.loadContextSummary(
    props.conversationId,
    selectedCredentialId.value,
    selectedModel.value,
  );
}

async function onCredentialChange(): Promise<void> {
  await loadModels(selectedCredentialId.value);
}

function sendQuickPrompt(text: string): void {
  if (isThisConvStreaming.value) return;
  input.value = text;
  void send();
}

async function send(): Promise<void> {
  const text = input.value.trim();
  if (
    !text ||
    isThisConvStreaming.value ||
    !canSendMessage.value ||
    !selectedCredentialId.value ||
    !selectedModel.value ||
    modelsLoadFailed.value ||
    attachmentError.value !== null ||
    attachmentLoading.value
  ) {
    return;
  }
  input.value = "";
  resetChatInputHeight();
  const payloadAttachment: AttachedFile | null = attachedFile.value;
  clearAttachment();
  await chatStore.sendMessage(
    props.conversationId,
    text,
    selectedCredentialId.value,
    selectedModel.value,
    payloadAttachment
      ? {
          name: payloadAttachment.name,
          kind: payloadAttachment.kind,
          content: payloadAttachment.content,
        }
      : null,
  );
  focusInputWhenReady();
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

function stopStreaming(): void {
  chatStore.cancelStreaming(props.conversationId);
  nextTick(() => {
    chatInputRef.value?.focus();
  });
}

onUnmounted(() => {
  window.removeEventListener(SHOWCASE_CHAT_DRAFT_EVENT, applyShowcaseDraft);
  window.removeEventListener("resize", updateMessageScrollbar);
  window.removeEventListener("pointermove", handleChatScrollbarPointerMove);
  window.removeEventListener("pointerup", handleChatScrollbarPointerUp);
  messagesResizeObserver?.disconnect();
  if (copiedMessageIdTimeout) clearTimeout(copiedMessageIdTimeout);
  speechRecognition.value?.stop();
});
</script>

<template>
  <div
    ref="chatRootRef"
    class="flex flex-col h-full outline-none relative"
    tabindex="-1"
    @keydown.capture="handleChatKeydown"
    @keyup.capture="handleChatKeydown"
    @dragenter="handleDragEnter"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
    <Transition name="drag-overlay">
      <div
        v-if="isDraggingFile"
        class="absolute inset-0 z-30 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary/60 bg-primary/5 pointer-events-none"
      >
        <div class="flex flex-col items-center gap-2 text-primary/70">
          <Paperclip class="w-10 h-10" />
          <p class="text-sm font-medium">
            Drop file to attach
          </p>
        </div>
      </div>
    </Transition>
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 sm:gap-4 p-3 sm:p-4 border-b border-border/50 shrink-0">
      <div class="flex items-center gap-2 min-w-0 shrink-0">
        <button
          v-if="!chatStore.isSidebarOpen"
          class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          title="Open chat list"
          @click="chatStore.toggleSidebar"
        >
          <ChevronRight class="w-4 h-4" />
        </button>
        <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <Bot class="w-5 h-5 text-primary" />
        </div>
        <div class="min-w-0">
          <div
            v-if="isTitleLoading"
            class="mt-[8px] h-5 w-36 rounded-md bg-muted animate-pulse"
          />
          <h2
            v-else
            class="text-base sm:text-lg font-semibold truncate"
          >
            {{ conversationTitle || 'Chat' }}
          </h2>
          <div
            v-if="isTitleLoading"
            class="mt-1.5 h-3.5 w-48 rounded-md bg-muted/70 animate-pulse"
          />
          <p
            v-else
            class="text-xs sm:text-sm text-muted-foreground truncate"
          >
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
              @change="onCredentialChange"
            >
              <option
                value=""
                disabled
              >
                Select...
              </option>
              <option
                v-for="cred in credentials"
                :key="cred.id"
                :value="cred.id"
              >
                {{ cred.name }}
              </option>
            </select>
            <ChevronDown class="chat-select-arrow pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground shrink-0" />
          </div>

          <div class="chat-select-wrap relative flex flex-col min-w-0 sm:max-w-[160px]">
            <select
              v-model="selectedModel"
              class="chat-select min-h-[44px] sm:min-h-0 sm:h-9 rounded-lg border border-input bg-background pl-3 pr-9 py-2.5 sm:py-0 text-sm disabled:opacity-50 touch-manipulation w-full truncate appearance-none cursor-pointer"
              :disabled="!selectedCredentialId || isLoadingModels || modelsLoadFailed"
            >
              <option
                value=""
                disabled
              >
                {{ isLoadingModels ? "Loading..." : modelsLoadFailed ? "Failed to load" : "Select..." }}
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
      </div>
    </div>

    <div class="chat-messages-region relative flex min-h-0 flex-1">
      <div
        id="chat-messages-scroll"
        ref="messagesScrollRef"
        class="chat-messages-scroll flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto py-4 pl-4 pr-8"
        @scroll="updateMessageScrollbar"
      >
        <div
          v-if="isShowingConversation && messages.length === 0 && !isThisConvStreaming && !chatStore.isLoadingMessages"
          class="mx-auto flex flex-1 w-full flex-col items-center justify-center self-center px-4 py-6 gap-3 max-w-lg"
        >
          <Bot class="w-10 h-10 sm:w-12 sm:h-12 text-primary opacity-50" />
          <p class="text-xs sm:text-sm text-muted-foreground text-center max-w-[280px] sm:max-w-none">
            Ask to run a workflow, list workflows, or ask about your data.
          </p>
          <div class="w-full flex flex-col gap-1.5 mt-2">
            <div
              v-for="(prompt, index) in chatStore.quickPrompts"
              :key="index"
              class="group flex items-center gap-2 rounded-xl border border-border/40 bg-muted/30 hover:bg-muted/60 hover:border-border/60 transition-colors cursor-pointer px-3.5 py-2.5"
              @click="qpEditingIndex !== index && sendQuickPrompt(prompt)"
            >
              <template v-if="qpEditingIndex === index">
                <input
                  v-model="qpEditingValue"
                  data-qp-edit
                  class="flex-1 text-sm bg-transparent border-0 outline-none"
                  @keydown="qpOnEditKeydown"
                  @blur="void qpCommitEdit()"
                  @click.stop
                >
              </template>
              <template v-else>
                <span class="flex-1 text-sm text-foreground/80 truncate">{{ prompt }}</span>
                <button
                  type="button"
                  class="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-muted/80 text-muted-foreground hover:text-foreground"
                  title="Edit prompt"
                  @click.stop="qpStartEdit(index)"
                >
                  <Pencil class="w-3.5 h-3.5" />
                </button>
              </template>
            </div>
          </div>
        </div>
        <div
          v-for="msg in messages"
          :key="msg.id"
          :class="['flex gap-3', msg.role === 'user' ? 'justify-end' : 'justify-start']"
        >
          <div
            v-if="msg.role === 'assistant'"
            class="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5"
          >
            <Bot class="w-4 h-4 text-primary" />
          </div>

          <div
            :class="[
              'group/message relative rounded-2xl px-4 py-2.5 pr-[4.25rem] text-sm leading-relaxed break-words',
              msg.workflowPreview ? 'w-[min(92%,920px)] max-w-[920px]' : 'max-w-[72%]',
              msg.role === 'user'
                ? 'bg-primary text-primary-foreground rounded-tr-sm'
                : 'bg-muted text-foreground rounded-tl-sm'
            ]"
          >
            <button
              type="button"
              class="absolute right-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-lg text-current opacity-60 transition-opacity hover:bg-black/10 sm:opacity-0 sm:group-hover/message:opacity-70 hover:opacity-100"
              :title="copiedMessageId === msg.id ? 'Copied' : 'Copy'"
              :aria-label="copiedMessageId === msg.id ? 'Copied' : 'Copy message'"
              @click="copyMessage(msg)"
            >
              <Check
                v-if="copiedMessageId === msg.id"
                class="w-3.5 h-3.5"
              />
              <Copy
                v-else
                class="w-3.5 h-3.5"
              />
            </button>
            <button
              type="button"
              class="absolute right-9 top-1.5 flex h-7 w-7 items-center justify-center rounded-lg text-current opacity-60 transition-opacity hover:bg-black/10 sm:opacity-0 sm:group-hover/message:opacity-70 hover:opacity-100"
              :title="tts.playingId.value === msg.id ? 'Stop' : 'Read aloud'"
              :aria-label="tts.playingId.value === msg.id ? 'Stop reading' : 'Read message aloud'"
              @click="readMessageAloud(msg)"
            >
              <Square
                v-if="tts.playingId.value === msg.id"
                class="w-3.5 h-3.5"
              />
              <Volume2
                v-else
                class="w-3.5 h-3.5"
              />
            </button>
            <div
              v-if="msg.role === 'assistant' && msg.tool_calls && msg.tool_calls.length > 0"
              class="mb-2 flex flex-col gap-1.5"
            >
              <ChatToolCall
                v-for="tc in msg.tool_calls"
                :key="tc.id"
                :tool-call="tc"
              />
            </div>
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="chat-markdown"
              @click="handleMarkdownImageClick"
              v-html="renderMarkdown(msg.content)"
            />
            <!-- eslint-enable vue/no-v-html -->
            <div
              v-if="msg.images && msg.images.length > 0"
              class="mt-2 flex flex-wrap gap-2"
            >
              <img
                v-for="(imgSrc, index) in msg.images"
                :key="`${msg.id}-${index}`"
                :src="imgSrc"
                alt="Generated image"
                class="max-h-48 max-w-full rounded-lg object-contain cursor-zoom-in border border-border/30 hover:border-border/60 transition-colors"
                @click.stop="imageLightboxSrc = imgSrc"
              >
            </div>
            <div
              v-if="msg.workflowPreview"
              class="mt-3 overflow-hidden rounded-xl border border-border/50 bg-background/70"
            >
              <div class="flex flex-col gap-2 border-b border-border/50 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                <div class="min-w-0">
                  <p class="truncate text-sm font-semibold">
                    {{ msg.workflowPreview.name }}
                  </p>
                  <p
                    v-if="msg.workflowPreview.description"
                    class="line-clamp-2 text-xs text-muted-foreground"
                  >
                    {{ msg.workflowPreview.description }}
                  </p>
                </div>
                <a
                  :href="msg.workflowPreview.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                >
                  <ExternalLink class="h-3.5 w-3.5" />
                  Open workflow
                </a>
              </div>
              <div
                :class="[
                  'min-h-0 w-full transition-[height] duration-200',
                  hasWorkflowPreviewSelection(msg.workflowPreview) ? 'h-[30rem] lg:h-64' : 'h-64',
                ]"
              >
                <ReadonlyCanvasPreview
                  :nodes="msg.workflowPreview.nodes"
                  :edges="msg.workflowPreview.edges"
                  :flow-key="msg.workflowPreview.id"
                  :selected-node="selectedWorkflowPreviewNodes[msg.workflowPreview.id] ?? null"
                  empty-message="No workflow preview"
                  :show-mini-map="false"
                  :show-controls="false"
                  :max-zoom="1.1"
                  :background-gap="28"
                  :framed="false"
                  @update:selected-node="(node) => setWorkflowPreviewSelection(msg.workflowPreview!.id, node)"
                />
              </div>
            </div>
            <div
              v-if="msg.attachmentName"
              class="mt-1.5 flex items-center gap-1 text-xs opacity-70"
            >
              <Paperclip class="w-3 h-3 shrink-0" />
              <span class="truncate">{{ msg.attachmentName }}</span>
            </div>
          </div>

          <div
            v-if="msg.role === 'user'"
            class="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5 text-xs font-semibold text-muted-foreground"
          >
            {{ userInitial }}
          </div>
        </div>

        <div
          v-if="isThisConvStreaming"
          class="flex gap-3 justify-start"
        >
          <div class="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
            <Bot class="w-4 h-4 text-primary" />
          </div>
          <div
            :class="[
              'rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm leading-relaxed bg-muted text-foreground break-words',
              streamState.workflowPreview ? 'w-[min(92%,920px)] max-w-[920px]' : 'max-w-[72%]',
            ]"
          >
            <div
              v-if="streamState.toolCalls.length > 0"
              class="mb-3 flex flex-col gap-1.5"
            >
              <ChatToolCall
                v-for="tc in streamState.toolCalls"
                :key="tc.id"
                :tool-call="tc"
              />
            </div>
            <!-- eslint-disable vue/no-v-html -->
            <div
              v-if="streamState.content"
              class="chat-markdown"
              @click="handleMarkdownImageClick"
              v-html="renderMarkdown(streamState.content)"
            />
            <!-- eslint-enable vue/no-v-html -->
            <div
              v-if="!streamState.content && streamState.images.length === 0"
              class="flex items-center gap-2 text-muted-foreground"
            >
              <span>{{ streamState.toolCalls.length > 0 ? "Preparing response..." : "Heyming..." }}</span>
            </div>
            <div
              v-if="streamState.images.length > 0"
              class="mt-2 flex flex-wrap gap-2"
            >
              <img
                v-for="(imgSrc, index) in streamState.images"
                :key="`streaming-${index}`"
                :src="imgSrc"
                alt="Generated image"
                class="max-h-48 max-w-full rounded-lg object-contain cursor-zoom-in border border-border/30 hover:border-border/60 transition-colors"
                @click.stop="imageLightboxSrc = imgSrc"
              >
            </div>
            <div
              v-if="streamState.workflowPreview"
              class="mt-3 overflow-hidden rounded-xl border border-border/50 bg-background/70"
            >
              <div class="flex flex-col gap-2 border-b border-border/50 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                <div class="min-w-0">
                  <p class="truncate text-sm font-semibold">
                    {{ streamState.workflowPreview.name }}
                  </p>
                  <p
                    v-if="streamState.workflowPreview.description"
                    class="line-clamp-2 text-xs text-muted-foreground"
                  >
                    {{ streamState.workflowPreview.description }}
                  </p>
                </div>
                <a
                  :href="streamState.workflowPreview.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                >
                  <ExternalLink class="h-3.5 w-3.5" />
                  Open workflow
                </a>
              </div>
              <div
                :class="[
                  'min-h-0 w-full transition-[height] duration-200',
                  hasWorkflowPreviewSelection(streamState.workflowPreview) ? 'h-[30rem] lg:h-64' : 'h-64',
                ]"
              >
                <ReadonlyCanvasPreview
                  :nodes="streamState.workflowPreview.nodes"
                  :edges="streamState.workflowPreview.edges"
                  :flow-key="streamState.workflowPreview.id"
                  :selected-node="selectedWorkflowPreviewNodes[streamState.workflowPreview.id] ?? null"
                  empty-message="No workflow preview"
                  :show-mini-map="false"
                  :show-controls="false"
                  :max-zoom="1.1"
                  :background-gap="28"
                  :framed="false"
                  @update:selected-node="(node) => setWorkflowPreviewSelection(streamState.workflowPreview!.id, node)"
                />
              </div>
            </div>
          </div>
        </div>

        <div
          v-if="streamState.error"
          class="flex gap-3 justify-start"
        >
          <div class="w-7 h-7 rounded-full bg-destructive/10 flex items-center justify-center shrink-0 mt-0.5">
            <TriangleAlert class="w-4 h-4 text-destructive" />
          </div>
          <div class="max-w-[72%] rounded-2xl rounded-tl-sm border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-sm leading-relaxed text-destructive break-words">
            <p class="font-medium">
              Chat error
            </p>
            <p class="mt-1 whitespace-pre-wrap">
              {{ streamState.error }}
            </p>
          </div>
        </div>

        <div ref="messagesEndRef" />
      </div>
      <div
        ref="chatScrollbarTrackRef"
        class="chat-scrollbar-track"
        :class="{ 'chat-scrollbar-track--dragging': isDraggingChatScrollbar }"
        role="scrollbar"
        aria-controls="chat-messages-scroll"
        aria-orientation="vertical"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="chatScrollbarAriaValueNow"
        @pointerdown="handleChatScrollbarTrackPointerDown"
      >
        <div
          class="chat-scrollbar-thumb"
          :style="chatScrollbarThumbStyle"
          @pointerdown.stop="handleChatScrollbarThumbPointerDown"
        />
      </div>
    </div>

    <ImageLightbox
      :src="imageLightboxSrc"
      alt="Generated image"
      @close="imageLightboxSrc = null"
    />

    <InteractiveVoiceMode
      :open="interactiveVoiceOpen"
      :messages="messages"
      :is-streaming="isThisConvStreaming"
      :on-send="sendVoiceText"
      @close="interactiveVoiceOpen = false"
    />

    <div class="chat-input-area shrink-0 px-3 sm:px-4 pt-3 sm:pt-4 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <input
        ref="fileInputRef"
        type="file"
        accept=".txt,.csv,.json,.md,.py,.ts,.js,.html,.xml,.yaml,.yml,.log,.jpg,.jpeg,.png,.gif,.webp,.pdf"
        class="hidden"
        @change="handleFileInputChange"
      >
      <div class="flex items-center justify-between gap-2 mb-1.5 px-1">
        <ChatContextBadge
          :context-usage="contextUsageForBadge"
          :draft-tokens="draftTokens"
        />
        <div class="flex items-center gap-2 min-w-0">
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
      </div>
      <form
        class="flex items-center gap-2 rounded-2xl bg-muted/40 border border-border/40 px-3 py-2 min-h-[52px] focus-within:border-primary/30 focus-within:bg-muted/50 transition-colors"
        @submit.prevent="send"
      >
        <button
          type="button"
          class="shrink-0 h-9 w-9 min-h-[36px] min-w-[36px] rounded-xl flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/80 disabled:opacity-50 disabled:pointer-events-none touch-manipulation transition-colors"
          :disabled="isThisConvStreaming || attachmentLoading"
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
        <textarea
          ref="chatInputRef"
          v-model="input"
          rows="1"
          placeholder="Type a message..."
          class="chat-input flex-1 min-h-[44px] max-h-40 resize-none bg-transparent border-0 px-1 py-3 text-sm text-left focus:outline-none focus:ring-0 disabled:opacity-50 touch-manipulation placeholder:text-muted-foreground leading-5"
          :disabled="isThisConvStreaming || !canSendMessage || !selectedCredentialId || !selectedModel || modelsLoadFailed"
          @keydown="onKeydown"
          @input="resizeChatInput"
        />
        <button
          type="button"
          class="shrink-0 h-9 w-9 min-h-[36px] min-w-[36px] rounded-xl flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/80 disabled:opacity-50 disabled:pointer-events-none touch-manipulation transition-colors"
          :disabled="!canSendMessage || !selectedCredentialId || !selectedModel || modelsLoadFailed"
          title="Interactive voice mode"
          aria-label="Open interactive voice mode"
          @click="openInteractiveVoice"
        >
          <AudioLines class="w-4 h-4" />
        </button>
        <button
          v-if="isSpeechSupported"
          type="button"
          class="shrink-0 h-9 w-9 min-h-[36px] min-w-[36px] rounded-xl flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/80 disabled:opacity-50 disabled:pointer-events-none touch-manipulation transition-colors"
          :disabled="isThisConvStreaming || !canSendMessage || isFixingTranscription || !selectedCredentialId || !selectedModel || modelsLoadFailed"
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
          v-if="!isThisConvStreaming"
          type="submit"
          variant="gradient"
          size="icon"
          :disabled="!input.trim() || !canSendMessage || !selectedCredentialId || !selectedModel || modelsLoadFailed || !!attachmentError || attachmentLoading"
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
      <p
        v-if="credentialError"
        class="mt-2 text-xs text-destructive"
      >
        {{ credentialError }}
      </p>
    </div>
  </div>
</template>


<style scoped>
.chat-markdown :deep(p) {
  margin: 0.45em 0;
}

.chat-markdown :deep(p:first-child) {
  margin-top: 0;
}

.chat-markdown :deep(p:last-child) {
  margin-bottom: 0;
}

.chat-markdown :deep(ul),
.chat-markdown :deep(ol) {
  margin: 0.45em 0;
  padding-left: 1.25rem;
}

.chat-markdown :deep(blockquote) {
  border-left: 2px solid hsl(var(--border));
  margin: 0.6em 0;
  padding-left: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.chat-markdown :deep(code) {
  background: hsl(var(--background) / 0.65);
  border-radius: 0.25rem;
  font-size: 0.875em;
  padding: 0.125em 0.35em;
}

.chat-markdown :deep(pre) {
  background: hsl(var(--background) / 0.75);
  border-radius: 0.5rem;
  margin: 0.65em 0;
  overflow-x: auto;
  padding: 0.75rem;
}

.chat-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
}

.chat-messages-scroll {
  scrollbar-width: none;
}

.chat-messages-scroll::-webkit-scrollbar {
  height: 0;
  width: 0;
}

.chat-scrollbar-track {
  background: hsl(var(--muted-foreground) / 0.12);
  border-radius: 999px;
  bottom: 0.75rem;
  cursor: pointer;
  touch-action: none;
  position: absolute;
  right: 0.5rem;
  top: 0.75rem;
  width: 0.5rem;
  z-index: 2;
}

.chat-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.45);
  border-radius: 999px;
  cursor: grab;
  min-height: 44px;
  transition: background-color 120ms ease;
  touch-action: none;
  width: 100%;
}

.chat-scrollbar-thumb:hover,
.chat-scrollbar-track--dragging .chat-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.62);
}

.chat-scrollbar-track--dragging,
.chat-scrollbar-track--dragging .chat-scrollbar-thumb {
  cursor: grabbing;
}

.chat-markdown :deep(a) {
  color: inherit;
  text-decoration: underline;
}

.chat-markdown :deep(img),
.chat-markdown :deep(video) {
  border: 1px solid hsl(var(--border) / 0.35);
  border-radius: 0.5rem;
  cursor: zoom-in;
  margin: 0.65rem 0;
  max-height: 12rem;
  max-width: 100%;
  object-fit: contain;
}

.drag-overlay-enter-active,
.drag-overlay-leave-active {
  transition: opacity 150ms ease;
}

.drag-overlay-enter-from,
.drag-overlay-leave-to {
  opacity: 0;
}
</style>
