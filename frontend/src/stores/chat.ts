import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type { Conversation, ConversationDetail, ContextUsage, Message, ToolCall, WorkflowPreview } from "@/types/chat";
import type { FileAttachmentPayload } from "@/services/api";
import { chatApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

const DEFAULT_CONVERSATION_TITLE = "New Chat";
const SIDEBAR_OPEN_KEY = "heym-chat-sidebar-open";
const MOBILE_SIDEBAR_MEDIA_QUERY = "(max-width: 767px)";
const CHAT_CACHE_KEY_PREFIX = "heym-chat-cache";
const CHAT_CACHE_CRYPTO_CONTEXT = "heym-chat-cache-v1";

interface EncryptedChatCachePayload {
  v: 1;
  iv: string;
  data: string;
}

type ConversationLoadResult = "loaded" | "not_found" | "error";

function getInitialSidebarOpen(): boolean {
  if (typeof window === "undefined") return true;
  if (window.matchMedia(MOBILE_SIDEBAR_MEDIA_QUERY).matches) return false;
  return window.localStorage.getItem(SIDEBAR_OPEN_KEY) !== "false";
}

export const useChatStore = defineStore("chat", () => {
  const authStore = useAuthStore();
  const conversations = ref<Conversation[]>([]);
  const activeConversation = ref<ConversationDetail | null>(null);
  const isSidebarOpen = ref(getInitialSidebarOpen());
  const isLoadingConversations = ref(false);
  const isLoadingMessages = ref(false);
  interface StreamState {
    content: string;
    images: string[];
    toolCalls: ToolCall[];
    contextUsage: ContextUsage | null;
    workflowPreview: WorkflowPreview | null;
    error: string | null;
    isStreaming: boolean;
  }
  const EMPTY_STREAM_STATE: StreamState = Object.freeze({
    content: "",
    images: [],
    toolCalls: [],
    contextUsage: null,
    workflowPreview: null,
    error: null,
    isStreaming: false,
  }) as StreamState;
  const streamStatesByConv = ref<Record<string, StreamState>>({});
  const contextUsageByConv = ref<Record<string, ContextUsage>>({});
  const activeControllersByConv = new Map<string, AbortController>();
  const quickPrompts = ref<string[]>([]);
  let latestConversationLoadId: string | null = null;
  const backgroundSubscribedConvIds = new Set<string>();
  const foregroundSubscribedConvIds = new Set<string>();
  const userCancelledConvIds = new Set<string>();

  function getStreamState(conversationId: string | null | undefined): StreamState {
    if (!conversationId) return EMPTY_STREAM_STATE;
    return streamStatesByConv.value[conversationId] ?? EMPTY_STREAM_STATE;
  }

  function _setStreamState(conversationId: string, patch: Partial<StreamState>): void {
    const current = streamStatesByConv.value[conversationId] ?? {
      content: "",
      images: [],
      toolCalls: [],
      contextUsage: null,
      workflowPreview: null,
      error: null,
      isStreaming: false,
    };
    streamStatesByConv.value = {
      ...streamStatesByConv.value,
      [conversationId]: { ...current, ...patch },
    };
  }

  function _clearStreamState(conversationId: string): void {
    if (!(conversationId in streamStatesByConv.value)) return;
    const next = { ...streamStatesByConv.value };
    delete next[conversationId];
    streamStatesByConv.value = next;
  }

  const sortedConversations = computed<Conversation[]>(() =>
    [...conversations.value].sort((a, b) => {
      if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
    }),
  );

  function toggleSidebar(): void {
    setSidebarOpen(!isSidebarOpen.value);
  }

  function openSidebar(): void {
    setSidebarOpen(true);
  }

  function closeSidebar(): void {
    setSidebarOpen(false);
  }

  function setSidebarOpen(open: boolean): void {
    isSidebarOpen.value = open;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_OPEN_KEY, String(isSidebarOpen.value));
    }
  }

  async function loadConversations(): Promise<void> {
    isLoadingConversations.value = true;
    try {
      conversations.value = await chatApi.listConversations();
      for (const conv of conversations.value) {
        if (conv.is_running && !backgroundSubscribedConvIds.has(conv.id)) {
          void _subscribeToBackgroundStream(conv.id);
        }
      }
    } finally {
      isLoadingConversations.value = false;
    }
  }

  async function _subscribeToBackgroundStream(conversationId: string): Promise<void> {
    if (backgroundSubscribedConvIds.has(conversationId)) return;
    backgroundSubscribedConvIds.add(conversationId);
    const controller = new AbortController();
    try {
      await chatApi.subscribeStream(
        conversationId,
        () => {},
        () => {
          backgroundSubscribedConvIds.delete(conversationId);
          _patchConversationFlag(conversationId, "is_running", false);
          const isActive = activeConversation.value?.id === conversationId;
          if (!isActive) {
            _patchConversationFlag(conversationId, "has_unread", true);
            _playDing();
          }
          _refreshConversationTimestamp(conversationId);
        },
        () => {
          backgroundSubscribedConvIds.delete(conversationId);
          _patchConversationFlag(conversationId, "is_running", false);
        },
        undefined, // onToolStart
        undefined, // onToolEnd
        undefined, // onToolOutput
        (title) => { _patchConversationTitle(conversationId, title); },
        undefined, // onWorkflowCreated
        undefined, // onCompressed
        undefined, // onContext
        controller.signal,
      );
    } catch {
      backgroundSubscribedConvIds.delete(conversationId);
      _patchConversationFlag(conversationId, "is_running", false);
    }
  }

  async function loadConversation(id: string): Promise<ConversationLoadResult> {
    latestConversationLoadId = id;
    const existingConversation = activeConversation.value?.id === id ? activeConversation.value : null;
    isLoadingMessages.value = !existingConversation;
    try {
      if (!existingConversation) {
        const cached = await _readCachedConversation(id);
        if (latestConversationLoadId !== id) return "error";
        if (cached) {
          activeConversation.value = cached;
          isLoadingMessages.value = false;
        }
      }

      const fetched = await chatApi.getConversation(id);
      if (latestConversationLoadId !== id) return "error";
      const existingListTitle = conversations.value.find((c) => c.id === id)?.title;
      const reconciledFetched: ConversationDetail = _preserveTitleOverDefault(
        fetched,
        activeConversation.value?.id === id ? activeConversation.value.title : undefined,
        existingListTitle,
      );
      if (activeConversation.value?.id === id) {
        activeConversation.value = _mergeConversationDetails(
          activeConversation.value,
          reconciledFetched,
        );
      } else {
        activeConversation.value = reconciledFetched;
      }
      _patchConversation(reconciledFetched);
      void _writeCachedConversation(activeConversation.value);
      if (fetched.has_unread) {
        void markConversationRead(id);
      }
      if (
        fetched.is_running &&
        !foregroundSubscribedConvIds.has(id) &&
        !userCancelledConvIds.has(id)
      ) {
        void _subscribeToStream(id);
      }
      return "loaded";
    } catch (error) {
      const status = _getHttpStatus(error);
      if (status === 400 || status === 404 || status === 422) {
        conversations.value = conversations.value.filter((conversation) => conversation.id !== id);
        _removeCachedConversation(id);
        if (activeConversation.value?.id === id) {
          activeConversation.value = null;
        }
        return "not_found";
      }
      return "error";
    } finally {
      if (latestConversationLoadId === id) {
        isLoadingMessages.value = false;
      }
    }
  }

  async function createConversation(title?: string): Promise<Conversation> {
    const conv = await chatApi.createConversation(title ? { title } : {});
    latestConversationLoadId = conv.id;
    if (!conversations.value.some((existing) => existing.id === conv.id)) {
      conversations.value = [conv, ...conversations.value];
    }
    const detail: ConversationDetail = {
      ...conv,
      last_credential_id: null,
      last_model: null,
      messages: [],
    };
    activeConversation.value = detail;
    void _writeCachedConversation(detail);
    return conv;
  }

  async function renameConversation(id: string, title: string): Promise<void> {
    const updated = await chatApi.updateConversation(id, { title });
    _patchConversation(updated);
    if (activeConversation.value?.id === id) {
      activeConversation.value = { ...activeConversation.value, title: updated.title };
    }
  }

  async function togglePin(id: string): Promise<void> {
    const conv = conversations.value.find((c) => c.id === id);
    if (!conv) return;
    const updated = await chatApi.updateConversation(id, { is_pinned: !conv.is_pinned });
    // Backend may return a stale "New Chat" title if the conversation is mid-stream
    // (the title commit happens at the end of _process_chat). Preserve the better
    // in-memory title in that case.
    const preserved: Conversation =
      updated.title === DEFAULT_CONVERSATION_TITLE && conv.title !== DEFAULT_CONVERSATION_TITLE
        ? { ...updated, title: conv.title }
        : updated;
    _patchConversation(preserved);
    if (activeConversation.value?.id === id && preserved.title !== updated.title) {
      activeConversation.value = { ...activeConversation.value, title: preserved.title };
    }
  }

  async function deleteConversation(id: string): Promise<void> {
    await chatApi.deleteConversation(id);
    conversations.value = conversations.value.filter((c) => c.id !== id);
    _removeCachedConversation(id);
    if (activeConversation.value?.id === id) {
      activeConversation.value = null;
    }
  }

  async function clearConversations(): Promise<void> {
    await chatApi.clearConversations();
    conversations.value = [];
    activeConversation.value = null;
    _clearCachedConversations();
  }

  async function sendMessage(
    conversationId: string,
    content: string,
    credentialId: string,
    model: string,
    attachment: FileAttachmentPayload | null = null,
  ): Promise<void> {
    if (!activeConversation.value || activeConversation.value.id !== conversationId) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      ...(attachment ? { attachmentName: attachment.name } : {}),
      created_at: new Date().toISOString(),
    };
    const isFirstMessage = activeConversation.value.messages.length === 0;
    activeConversation.value = {
      ...activeConversation.value,
      messages: [...activeConversation.value.messages, userMessage],
    };
    void _writeCachedConversation(activeConversation.value);

    if (isFirstMessage && activeConversation.value.title === DEFAULT_CONVERSATION_TITLE) {
      const immediateTitle = _titleFromContent(content);
      _patchConversationTitle(conversationId, immediateTitle);
    }

    _setStreamState(conversationId, {
      content: "",
      images: [],
      toolCalls: [],
      contextUsage: null,
      workflowPreview: null,
      error: null,
      isStreaming: true,
    });

    userCancelledConvIds.delete(conversationId);

    try {
      await chatApi.sendMessage(conversationId, content, credentialId, model, attachment);
      _patchConversationFlag(conversationId, "is_running", true);
      void _subscribeToStream(conversationId);
    } catch {
      _clearStreamState(conversationId);
    }
  }

  async function _subscribeToStream(conversationId: string): Promise<void> {
    // Avoid double-subscribing for the same conversation. This prevents a
    // race where loadConversation sees a stale `fetched.is_running=true`
    // shortly after the stream has finished locally — without this guard,
    // the resulting re-subscription would reset streamingSteps/Content and
    // make the UI look empty until the backend returns its (immediate) done.
    if (foregroundSubscribedConvIds.has(conversationId)) return;
    foregroundSubscribedConvIds.add(conversationId);

    const controller = new AbortController();
    activeControllersByConv.set(conversationId, controller);

    _setStreamState(conversationId, {
      content: "",
      images: [],
      toolCalls: [],
      contextUsage: null,
      workflowPreview: null,
      error: null,
      isStreaming: true,
    });

    try {
      await chatApi.subscribeStream(
        conversationId,
        (text) => {
          const current = getStreamState(conversationId);
          _setStreamState(conversationId, { content: current.content + text });
        },
        () => {
          const final = getStreamState(conversationId);
          const hasContent =
            final.content.length > 0 ||
            final.images.length > 0 ||
            final.workflowPreview !== null ||
            final.toolCalls.length > 0;
          if (hasContent && activeConversation.value?.id === conversationId) {
            const assistantMessage: Message = {
              id: crypto.randomUUID(),
              role: "assistant",
              content: final.content,
              ...(final.images.length > 0 ? { images: [...final.images] } : {}),
              ...(final.workflowPreview ? { workflowPreview: final.workflowPreview } : {}),
              ...(final.toolCalls.length > 0 ? { tool_calls: [...final.toolCalls] } : {}),
              created_at: new Date().toISOString(),
            };
            activeConversation.value = {
              ...activeConversation.value,
              messages: [...activeConversation.value.messages, assistantMessage],
            };
            void _writeCachedConversation(activeConversation.value);
          }
          _clearStreamState(conversationId);
          _patchConversationFlag(conversationId, "is_running", false);
          if (activeConversation.value?.id !== conversationId) {
            _patchConversationFlag(conversationId, "has_unread", true);
          }
          _refreshConversationTimestamp(conversationId);
          if (hasContent) _playDing();
        },
        (message) => {
          const cleanMessage = message.trim() || "Dashboard chat failed";
          _setStreamState(conversationId, { error: cleanMessage, isStreaming: false });
          _patchConversationFlag(conversationId, "is_running", false);
        },
        (payload) => {
          const current = getStreamState(conversationId);
          _setStreamState(conversationId, {
            toolCalls: [
              ...current.toolCalls,
              {
                id: payload.id,
                name: payload.name,
                label: payload.label,
                args: payload.args,
                status: "running",
              },
            ],
          });
        },
        (payload) => {
          const current = getStreamState(conversationId);
          _setStreamState(conversationId, {
            toolCalls: current.toolCalls.map((tc) =>
              tc.id === payload.id
                ? {
                    ...tc,
                    response_summary: payload.response_summary,
                    elapsed_ms: payload.elapsed_ms,
                    status: payload.status,
                  }
                : tc,
            ),
          });
        },
        (images) => {
          const current = getStreamState(conversationId);
          _setStreamState(conversationId, { images: [...current.images, ...images] });
        },
        (title) => {
          _patchConversationTitle(conversationId, title);
        },
        (workflow) => {
          _setStreamState(conversationId, { workflowPreview: workflow });
        },
        (payload) => {
          const current = getStreamState(conversationId);
          const synthetic: ToolCall = {
            id: `cmp_${Date.now()}`,
            name: "_context_compression",
            label: "Context compressed",
            args: { messages_compressed: payload.messages_compressed },
            response_summary: `~${Math.floor(payload.tokens_before / 1000)}k → ~${Math.floor(payload.tokens_after / 1000)}k tokens`,
            elapsed_ms: payload.elapsed_ms,
            status: "compressed",
          };
          _setStreamState(conversationId, { toolCalls: [...current.toolCalls, synthetic] });
        },
        (payload) => {
          _setStreamState(conversationId, { contextUsage: payload });
          contextUsageByConv.value = { ...contextUsageByConv.value, [conversationId]: payload };
        },
        controller.signal,
      );
    } catch {
      if (!controller.signal.aborted) {
        _setStreamState(conversationId, {
          error: "Dashboard chat failed",
          isStreaming: false,
        });
        _patchConversationFlag(conversationId, "is_running", false);
      }
    } finally {
      foregroundSubscribedConvIds.delete(conversationId);
      if (activeControllersByConv.get(conversationId) === controller) {
        activeControllersByConv.delete(conversationId);
      }
    }
  }

  async function markConversationRead(id: string): Promise<void> {
    _patchConversationFlag(id, "has_unread", false);
    await chatApi.markConversationRead(id);
  }

  async function loadQuickPrompts(): Promise<void> {
    try {
      quickPrompts.value = await chatApi.getQuickPrompts();
    } catch {
      // Keep empty; UI falls back to defaults
    }
  }

  async function saveQuickPrompts(prompts: string[]): Promise<void> {
    const saved = await chatApi.saveQuickPrompts(prompts);
    quickPrompts.value = saved;
  }

  async function loadContextSummary(
    conversationId: string,
    credentialId: string,
    model: string,
  ): Promise<void> {
    try {
      const usage = await chatApi.getContextSummary(conversationId, credentialId, model);
      contextUsageByConv.value = { ...contextUsageByConv.value, [conversationId]: usage };
    } catch {
      // best-effort; UI falls back to hiding the badge
    }
  }

  function cancelStreaming(conversationId: string): void {
    const controller = activeControllersByConv.get(conversationId);
    userCancelledConvIds.add(conversationId);
    controller?.abort();
    activeControllersByConv.delete(conversationId);
    foregroundSubscribedConvIds.delete(conversationId);
    const current = getStreamState(conversationId);
    _setStreamState(conversationId, {
      isStreaming: false,
      toolCalls: current.toolCalls.map((tc) =>
        tc.status === "running"
          ? { ...tc, status: "cancelled" as const, response_summary: "Cancelled" }
          : tc,
      ),
    });
    _patchConversationFlag(conversationId, "is_running", false);
    // Tell the backend to stop the running agent task, not just the local reader.
    void chatApi.cancelStream(conversationId).catch(() => {});
  }

  function _patchConversation(updated: Conversation): void {
    conversations.value = conversations.value.map((c) => (c.id === updated.id ? updated : c));
  }

  function _patchConversationFlag(
    id: string,
    flag: "is_running" | "has_unread",
    value: boolean,
  ): void {
    conversations.value = conversations.value.map((c) =>
      c.id === id ? { ...c, [flag]: value } : c,
    );
  }

  function _playDing(): void {
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.25, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.4);
    } catch {
      // AudioContext unavailable — silent fail
    }
  }

  function _titleFromContent(content: string): string {
    const attachmentIdx = content.indexOf("\n\n[ATTACHED FILE:");
    const cleaned = (attachmentIdx !== -1 ? content.slice(0, attachmentIdx) : content).trim().replace(/^["'`“‘”’]+|["'`“‘”’]+$/g, "");
    if (!cleaned) return DEFAULT_CONVERSATION_TITLE;
    if (cleaned.length > 50) {
      const boundary = cleaned.indexOf(" ", 50);
      const cut = boundary !== -1 ? cleaned.slice(0, boundary) : cleaned.slice(0, 50);
      return `${cut.replace(/[.,:;!?]+$/, "")}...`;
    }
    return `${cleaned.replace(/[.,:;!?]+$/, "")}...`;
  }

  function _patchConversationTitle(id: string, title: string): void {
    const updatedAt = new Date().toISOString();
    conversations.value = conversations.value.map((c) =>
      c.id === id ? { ...c, title, updated_at: updatedAt } : c,
    );
    if (activeConversation.value?.id === id) {
      activeConversation.value = {
        ...activeConversation.value,
        title,
        updated_at: updatedAt,
      };
      void _writeCachedConversation(activeConversation.value);
    }
  }

  function _preserveTitleOverDefault(
    fetched: ConversationDetail,
    activeTitle: string | undefined,
    listTitle: string | undefined,
  ): ConversationDetail {
    if (fetched.title !== DEFAULT_CONVERSATION_TITLE) return fetched;
    const candidate = [activeTitle, listTitle].find(
      (t): t is string => typeof t === "string" && t !== DEFAULT_CONVERSATION_TITLE,
    );
    return candidate ? { ...fetched, title: candidate } : fetched;
  }

  function _mergeConversationDetails(
    current: ConversationDetail,
    fetched: ConversationDetail,
  ): ConversationDetail {
    if (current.messages.length === 0) {
      return fetched;
    }
    if (fetched.messages.length <= current.messages.length) {
      return {
        ...fetched,
        messages: current.messages,
      };
    }
    return {
      ...fetched,
      messages: [...current.messages, ...fetched.messages.slice(current.messages.length)],
    };
  }

  async function _readCachedConversation(id: string): Promise<ConversationDetail | null> {
    if (!window.crypto?.subtle) return null;
    try {
      const storageKey = _getCachedConversationStorageKey(id);
      if (!storageKey) return null;
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) return null;
      const payload = JSON.parse(raw) as EncryptedChatCachePayload;
      if (payload.v !== 1) return null;
      const key = await _getChatCacheCryptoKey();
      if (!key) return null;
      const iv = _base64ToBytes(payload.iv);
      const data = _base64ToBytes(payload.data);
      const decrypted = await window.crypto.subtle.decrypt(
        { name: "AES-GCM", iv: _bytesToArrayBuffer(iv) },
        key,
        _bytesToArrayBuffer(data),
      );
      return JSON.parse(new TextDecoder().decode(decrypted)) as ConversationDetail;
    } catch {
      _removeCachedConversation(id);
      return null;
    }
  }

  async function _writeCachedConversation(conversation: ConversationDetail): Promise<void> {
    if (!window.crypto?.subtle) return;
    try {
      const storageKey = _getCachedConversationStorageKey(conversation.id);
      if (!storageKey) return;
      const key = await _getChatCacheCryptoKey();
      if (!key) return;
      const iv = window.crypto.getRandomValues(new Uint8Array(12));
      const plaintext = new TextEncoder().encode(JSON.stringify(conversation));
      const encrypted = await window.crypto.subtle.encrypt(
        { name: "AES-GCM", iv: _bytesToArrayBuffer(iv) },
        key,
        _bytesToArrayBuffer(plaintext),
      );
      const payload: EncryptedChatCachePayload = {
        v: 1,
        iv: _bytesToBase64(iv),
        data: _bytesToBase64(new Uint8Array(encrypted)),
      };
      window.localStorage.setItem(storageKey, JSON.stringify(payload));
    } catch {
      // Cache writes are best-effort; chat still works from the backend.
    }
  }

  async function _getChatCacheCryptoKey(): Promise<CryptoKey | null> {
    if (!window.crypto?.subtle) return null;
    const userId = _getCurrentUserId();
    if (!userId) return null;
    const keyMaterial = await window.crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(`${CHAT_CACHE_CRYPTO_CONTEXT}:${userId}`),
    );
    return window.crypto.subtle.importKey(
      "raw",
      keyMaterial,
      "AES-GCM",
      false,
      ["encrypt", "decrypt"],
    );
  }

  function _removeCachedConversation(id: string): void {
    const storageKey = _getCachedConversationStorageKey(id);
    if (storageKey) {
      window.localStorage.removeItem(storageKey);
    }
  }

  function _clearCachedConversations(): void {
    const userId = _getCurrentUserId();
    const prefix = userId ? `${CHAT_CACHE_KEY_PREFIX}:${userId}:` : `${CHAT_CACHE_KEY_PREFIX}:`;
    const keys = Array.from({ length: window.localStorage.length }, (_, index) =>
      window.localStorage.key(index),
    ).filter((key): key is string => key?.startsWith(prefix) ?? false);
    keys.forEach((key) => window.localStorage.removeItem(key));
  }

  function _getCachedConversationStorageKey(id: string): string | null {
    const userId = _getCurrentUserId();
    return userId ? `${CHAT_CACHE_KEY_PREFIX}:${userId}:${id}` : null;
  }

  function _getCurrentUserId(): string | null {
    return authStore.user?.id ?? null;
  }

  function _getHttpStatus(error: unknown): number | null {
    if (typeof error !== "object" || error === null || !("response" in error)) {
      return null;
    }
    const response = (error as { response?: unknown }).response;
    if (typeof response !== "object" || response === null || !("status" in response)) {
      return null;
    }
    const status = (response as { status?: unknown }).status;
    return typeof status === "number" ? status : null;
  }

  function _bytesToBase64(bytes: Uint8Array): string {
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    return window.btoa(binary);
  }

  function _base64ToBytes(value: string): Uint8Array {
    const binary = window.atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }

  function _bytesToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  }

  function _refreshConversationTimestamp(id: string): void {
    conversations.value = conversations.value.map((c) =>
      c.id === id ? { ...c, updated_at: new Date().toISOString() } : c,
    );
    if (activeConversation.value?.id === id) {
      activeConversation.value = {
        ...activeConversation.value,
        updated_at: new Date().toISOString(),
      };
      void _writeCachedConversation(activeConversation.value);
    }
  }

  return {
    conversations,
    sortedConversations,
    activeConversation,
    isSidebarOpen,
    isLoadingConversations,
    isLoadingMessages,
    streamStatesByConv,
    contextUsageByConv,
    getStreamState,
    quickPrompts,
    toggleSidebar,
    openSidebar,
    closeSidebar,
    loadConversations,
    loadConversation,
    createConversation,
    renameConversation,
    togglePin,
    deleteConversation,
    clearConversations,
    sendMessage,
    cancelStreaming,
    markConversationRead,
    loadQuickPrompts,
    saveQuickPrompts,
    loadContextSummary,
  };
});
