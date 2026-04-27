import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

import type { CredentialListItem, LLMModel } from "@/types/credential";
import { aiApi, credentialsApi } from "@/services/api";

export interface DocsChatDialogProps {
  open: boolean;
  docPath: string | null;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

const MAX_CONTEXT_MESSAGES = 25;

export function useDocsChatDialog(props: DocsChatDialogProps, onClose: () => void) {
  const credentials = ref<CredentialListItem[]>([]);
  const models = ref<LLMModel[]>([]);
  const selectedCredentialId = ref("");
  const selectedModel = ref("");
  const loadingModels = ref(false);
  const modelsLoadFailed = ref(false);
  const messages = ref<ChatMessage[]>([]);
  const inputText = ref("");
  const streaming = ref(false);
  const steps = ref<string[]>([]);
  const hasClearableContent = computed(() => messages.value.length > 0 || inputText.value.trim().length > 0 || streaming.value);
  const messagesContainer = ref<HTMLElement | null>(null);
  const chatInputRef = ref<HTMLTextAreaElement | null>(null);
  const activeAbortController = ref<AbortController | null>(null);
  const activeAssistantMessageId = ref<string | null>(null);
  const copiedMessageId = ref<string | null>(null);
  let activeStreamSequence = 0;
  let activeFlushPromise: Promise<void> = Promise.resolve();
  let copiedMessageIdTimeout: ReturnType<typeof setTimeout> | null = null;

  function pickDefaultModel(modelList: LLMModel[]): string {
    if (modelList.length === 0) return "";
    const lower = (value: string) => value.toLowerCase();
    const isPreferred = (model: LLMModel) => lower(model.name).includes("cerebras") || lower(model.name).includes("glm") || lower(model.id).includes("cerebras") || lower(model.id).includes("glm");
    const preferred = modelList.filter(isPreferred);
    return preferred.length > 0 ? preferred[preferred.length - 1].id : modelList[modelList.length - 1].id;
  }

  async function loadCredentials(): Promise<void> {
    try {
      credentials.value = await credentialsApi.listLLM();
      if (credentials.value.length > 0 && !selectedCredentialId.value) selectedCredentialId.value = credentials.value[0].id;
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
      selectedModel.value = models.value.length > 0 ? pickDefaultModel(models.value) : "";
    } catch {
      models.value = [];
      modelsLoadFailed.value = true;
      selectedModel.value = "";
    } finally {
      loadingModels.value = false;
    }
  }

  function focusChatInput(): void { nextTick(() => chatInputRef.value?.focus()); }
  function scrollToBottom(): void { nextTick(() => messagesContainer.value?.scrollTo({ top: messagesContainer.value.scrollHeight, behavior: "smooth" })); }
  function scrollToBottomImmediate(): void { if (messagesContainer.value) messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight; }
  function bumpStreamSequence(): number {
    activeStreamSequence += 1;
    activeFlushPromise = Promise.resolve();
    return activeStreamSequence;
  }

  function queueStreamChunk(assistantId: string, chunk: string, sequence: number): void {
    const sliceSize = chunk.length > 120 ? 18 : 8;
    activeFlushPromise = activeFlushPromise.then(async () => {
      for (let index = 0; index < chunk.length; index += sliceSize) {
        if (sequence !== activeStreamSequence) return;
        const message = messages.value.find((entry) => entry.id === assistantId);
        if (!message || message.role !== "assistant") return;
        message.content += chunk.slice(index, index + sliceSize);
        await nextTick();
        scrollToBottomImmediate();
        if (index + sliceSize < chunk.length) await new Promise((resolve) => window.setTimeout(resolve, 14));
      }
    });
  }

  function renderMarkdown(content: string): string {
    if (!content) return "";
    const html = marked(content, { breaks: true, gfm: true }) as string;
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: ["p", "br", "strong", "em", "u", "s", "code", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "hr", "table", "thead", "tbody", "tr", "th", "td", "img"],
      ALLOWED_ATTR: ["href", "target", "rel", "src", "alt"],
    });
  }

  function resetSession(): void {
    bumpStreamSequence();
    activeAbortController.value?.abort();
    messages.value = [];
    inputText.value = "";
    streaming.value = false;
    steps.value = [];
    activeAbortController.value = null;
    activeAssistantMessageId.value = null;
  }

  function clearChat(): void {
    resetSession();
    nextTick(focusChatInput);
  }

  function buildConversationHistory(): Array<{ role: "user" | "assistant"; content: string }> {
    return messages.value.filter((message) => message.role === "user" || message.role === "assistant").slice(0, -2).slice(-MAX_CONTEXT_MESSAGES).map((message) => ({ role: message.role, content: message.content }));
  }

  function handleSubmit(): void {
    const text = inputText.value.trim();
    if (!text || streaming.value || !selectedCredentialId.value || !selectedModel.value) return;
    messages.value.push({ id: crypto.randomUUID(), role: "user", content: text });
    inputText.value = "";
    const assistantId = crypto.randomUUID();
    messages.value.push({ id: assistantId, role: "assistant", content: "" });
    activeAssistantMessageId.value = assistantId;
    streaming.value = true;
    steps.value = [];
    const streamSequence = bumpStreamSequence();
    const abortController = new AbortController();
    activeAbortController.value = abortController;
    aiApi.dashboardChatStream(
      {
        credentialId: selectedCredentialId.value,
        model: selectedModel.value,
        message: text,
        conversationHistory: buildConversationHistory(),
        chatSurface: "documentation",
        userRules: props.docPath ? `The user is currently reading the Heym documentation page: /docs/${props.docPath}. Prioritize answers relevant to this page.` : undefined,
        clientLocalDatetime: new Date().toLocaleString(),
      },
      (chunk) => queueStreamChunk(assistantId, chunk, streamSequence),
      () => {
        void activeFlushPromise.finally(() => {
          if (streamSequence !== activeStreamSequence) return;
          streaming.value = false;
          activeAbortController.value = null;
          activeAssistantMessageId.value = null;
        });
      },
      (error) => {
        void activeFlushPromise.finally(() => {
          if (streamSequence !== activeStreamSequence) return;
          streaming.value = false;
          activeAbortController.value = null;
          activeAssistantMessageId.value = null;
          if (error.name === "AbortError") return;
          const message = messages.value.find((entry) => entry.id === assistantId);
          if (message && message.role === "assistant") message.content = message.content || `Error: ${error.message}`;
        });
      },
      abortController.signal,
      (label) => { steps.value = [...steps.value, label]; },
    );
  }

  function stopStreaming(): void {
    if (!streaming.value) return;
    bumpStreamSequence();
    activeAbortController.value?.abort();
    streaming.value = false;
    const assistantId = activeAssistantMessageId.value;
    if (assistantId) {
      const index = messages.value.findIndex((message) => message.id === assistantId);
      const message = index >= 0 ? messages.value[index] : null;
      if (message && message.role === "assistant" && !message.content.trim()) messages.value.splice(index, 1);
    }
    activeAbortController.value = null;
    activeAssistantMessageId.value = null;
    steps.value = [];
    focusChatInput();
  }

  async function copyMessageContent(message: ChatMessage): Promise<void> {
    const text = message.content || "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      copiedMessageId.value = message.id;
      if (copiedMessageIdTimeout) clearTimeout(copiedMessageIdTimeout);
      copiedMessageIdTimeout = setTimeout(() => {
        copiedMessageId.value = null;
      }, 2000);
    } catch {
      // ignore clipboard errors
    }
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); handleSubmit(); }
  }

  function handleClose(): void { resetSession(); onClose(); }

  watch(selectedCredentialId, () => { void loadModels(); });
  watch(() => messages.value.length, scrollToBottom, { flush: "post" });
  watch(() => messages.value.at(-1)?.content, () => { if (streaming.value) nextTick(scrollToBottomImmediate); }, { flush: "post" });
  watch([selectedCredentialId, selectedModel], () => { if (props.open && selectedCredentialId.value && selectedModel.value) focusChatInput(); });
  watch(() => props.open, (open) => {
    if (open) {
      if (credentials.value.length === 0) void loadCredentials();
      else if (selectedCredentialId.value && models.value.length === 0 && !loadingModels.value) void loadModels();
      focusChatInput();
      return;
    }
    resetSession();
  }, { immediate: true });

  onUnmounted(() => {
    activeAbortController.value?.abort();
    if (copiedMessageIdTimeout) clearTimeout(copiedMessageIdTimeout);
  });

  return {
    credentials,
    models,
    selectedCredentialId,
    selectedModel,
    loadingModels,
    modelsLoadFailed,
    messages,
    inputText,
    streaming,
    steps,
    hasClearableContent,
    copiedMessageId,
    messagesContainer,
    chatInputRef,
    renderMarkdown,
    clearChat,
    copyMessageContent,
    handleSubmit,
    stopStreaming,
    handleKeydown,
    handleClose,
  };
}
