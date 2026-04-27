<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { AlertCircle, Copy, Download, Eye, EyeOff, Loader2, Moon, Send, Square, Sun, Upload, Workflow } from "lucide-vue-next";
import { marked } from "marked";
import DOMPurify from "dompurify";

import Button from "@/components/ui/Button.vue";
import ImageLightbox from "@/components/ui/ImageLightbox.vue";
import { heymClientHeaders } from "@/constants/httpIdentity";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import WorkflowHeroBackground from "@/components/Layout/WorkflowHeroBackground.vue";
import { useThemeStore } from "@/stores/theme";
import { playSuccessSound } from "@/utils/audio";

interface PortalInfo {
  workflow_name: string;
  workflow_description: string | null;
  requires_auth: boolean;
  stream_enabled: boolean;
  file_upload_enabled: boolean;
  file_config: Record<string, { file_upload_enabled: boolean; allowed_types: string[]; max_size_mb: number }>;
  input_fields: Array<{ key: string; defaultValue?: string }>;
}

interface ChatMessage {
  id: string;
  type: "user" | "assistant" | "system" | "progress";
  content: string;
  timestamp: Date;
  images?: string[];
  nodeProgress?: string[];
  duration?: number;
}

const route = useRoute();
const themeStore = useThemeStore();
const slug = computed(() => route.params.slug as string);

const portalInfo = ref<PortalInfo | null>(null);
const isLoading = ref(true);
const error = ref("");
const getSessionTokenKey = (): string => `portal_session_${slug.value}`;
const sessionToken = ref<string | null>(localStorage.getItem(getSessionTokenKey()));

const username = ref("");
const password = ref("");
const showPassword = ref(false);
const isLoggingIn = ref(false);
const loginError = ref("");

const inputValues = ref<Record<string, string>>({});
const messages = ref<ChatMessage[]>([]);
const isExecuting = ref(false);
const currentProgress = ref<string[]>([]);
const activeAbortController = ref<AbortController | null>(null);
const activeExecutionId = ref<string | null>(null);
const stopRequested = ref(false);

const uploadedFiles = ref<Record<string, { name: string; type: string; content: string }>>({});
const messagesContainer = ref<HTMLElement | null>(null);
const isDragging = ref(false);
const dragCounter = ref(0);
const dragTargetField = ref<string | null>(null);
const fieldDragCounters = ref<Record<string, number>>({});
const copiedMessageId = ref<string | null>(null);
const activeMessageId = ref<string | null>(null);
const imageLightboxSrc = ref<string | null>(null);
const messageWidths = ref<Record<string, number>>({});
const isDraggingResize = ref(false);

const API_URL = import.meta.env.VITE_API_URL || "";

function scrollToBottom(): void {
  nextTick(() => {
    setTimeout(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTo({
          top: messagesContainer.value.scrollHeight,
          behavior: "smooth",
        });
      }
    }, 100);
  });
}

watch(() => messages.value.length, () => scrollToBottom(), { flush: "post" });
watch(() => currentProgress.value.length, () => scrollToBottom(), { flush: "post" });

const isAuthenticated = computed(() => {
  if (!portalInfo.value) return false;
  if (!portalInfo.value.requires_auth) return true;
  return !!sessionToken.value;
});

const visibleInputFields = computed(() => {
  return (portalInfo.value?.input_fields || []).filter((field) => field.key !== "infoNote");
});

const hasAnyInput = computed(() => {
  if (visibleInputFields.value.length === 0) return true;
  return visibleInputFields.value.some((field) => {
    const value = inputValues.value[field.key];
    return value && value.trim().length > 0;
  });
});

const hasResponses = computed(() => messages.value.some(m => m.type === "assistant"));

const MAX_CONVERSATION_HISTORY = 10;

const conversationHistory = computed(() => {
  const history: Array<{ role: string; content: string }> = [];
  const relevantMessages = messages.value.filter(
    (m) => m.type === "user" || m.type === "assistant"
  );
  const recentMessages = relevantMessages.slice(-MAX_CONVERSATION_HISTORY);
  for (const msg of recentMessages) {
    history.push({
      role: msg.type === "user" ? "user" : "assistant",
      content: msg.content,
    });
  }
  return history;
});

const unsubDismissOverlays = onDismissOverlays(() => {
  imageLightboxSrc.value = null;
});

const originalTitle = ref(document.title);
const hasPendingNotification = ref(false);

function handleVisibilityChange(): void {
  if (!document.hidden && hasPendingNotification.value) {
    hasPendingNotification.value = false;
    document.title = originalTitle.value;
  }
}

function notifyResponse(): void {
  playSuccessSound();
  if (document.hidden) {
    hasPendingNotification.value = true;
    document.title = `(1) ${originalTitle.value}`;
  }
}

onMounted(async () => {
  const savedToken = localStorage.getItem(getSessionTokenKey());
  if (savedToken) {
    sessionToken.value = savedToken;
  }
  await loadPortalInfo();
  document.addEventListener("click", handleClickOutside);
  document.addEventListener("visibilitychange", handleVisibilityChange);
  if (isAuthenticated.value && visibleInputFields.value.length > 0) {
    focusChatInput();
  }
});

onUnmounted(() => {
  activeAbortController.value?.abort();
  unsubDismissOverlays();
  document.removeEventListener("click", handleClickOutside);
  document.removeEventListener("visibilitychange", handleVisibilityChange);
  if (hasPendingNotification.value) {
    document.title = originalTitle.value;
  }
});

async function loadPortalInfo(): Promise<void> {
  isLoading.value = true;
  error.value = "";
  try {
    const response = await fetch(`${API_URL}/api/portal/${slug.value}/info`, {
      headers: { ...heymClientHeaders },
    });
    if (!response.ok) {
      if (response.status === 404) {
        error.value = "Portal not found";
      } else {
        error.value = "Failed to load portal";
      }
      return;
    }
    portalInfo.value = await response.json();
    initializeInputValues();
  } catch {
    error.value = "Failed to connect to server";
  } finally {
    isLoading.value = false;
  }
}

function initializeInputValues(): void {
  if (!portalInfo.value) return;
  const values: Record<string, string> = {};
  for (const field of portalInfo.value.input_fields) {
    values[field.key] = field.defaultValue || "";
  }
  inputValues.value = values;
}

async function handleLogin(): Promise<void> {
  if (!username.value.trim() || !password.value) return;

  isLoggingIn.value = true;
  loginError.value = "";
  try {
    const response = await fetch(`${API_URL}/api/portal/${slug.value}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...heymClientHeaders },
      body: JSON.stringify({ username: username.value, password: password.value }),
    });

    if (!response.ok) {
      const data = await response.json();
      loginError.value = data.detail || "Login failed";
      return;
    }

    const data = await response.json();
    const token = data.session_token;
    sessionToken.value = token;
    localStorage.setItem(getSessionTokenKey(), token);
    password.value = "";
    await nextTick();
    focusChatInput();
  } catch {
    loginError.value = "Connection error";
  } finally {
    isLoggingIn.value = false;
  }
}

async function handleFileUpload(event: Event, fieldKey: string): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;

  await processFile(file, fieldKey);
  input.value = "";
}

function readFile(file: File, asDataUrl: boolean): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => resolve(e.target?.result as string);
    reader.onerror = reject;
    if (asDataUrl) {
      reader.readAsDataURL(file);
    } else {
      reader.readAsText(file);
    }
  });
}

async function processFile(file: File, fieldKey: string): Promise<void> {
  const config = portalInfo.value?.file_config[fieldKey];
  const maxSize = (config?.max_size_mb || 5) * 1024 * 1024;

  if (file.size > maxSize) {
    alert(`File too large. Maximum size is ${config?.max_size_mb || 5}MB`);
    return;
  }

  const isImage = file.type.startsWith("image/");

  try {
    const content = await readFile(file, isImage);
    inputValues.value[fieldKey] = content;
    uploadedFiles.value[fieldKey] = { name: file.name, type: isImage ? "image" : "text", content };
    nextTick(() => resizeTextarea(fieldKey));
  } catch {
    alert("Failed to read file");
  }
}

function handleDragEnter(e: DragEvent): void {
  e.preventDefault();
  if (!portalInfo.value?.file_upload_enabled || visibleInputFields.value.length === 0) return;
  dragCounter.value++;
  if (e.dataTransfer?.types.includes("Files")) {
    isDragging.value = true;
  }
}

function handleDragLeave(e: DragEvent): void {
  e.preventDefault();
  if (!portalInfo.value?.file_upload_enabled || visibleInputFields.value.length === 0) return;
  dragCounter.value--;
  if (dragCounter.value === 0) {
    isDragging.value = false;
  }
}

function handleDragOver(e: DragEvent): void {
  e.preventDefault();
}

async function handleDrop(e: DragEvent, fieldKey?: string): Promise<void> {
  e.preventDefault();
  isDragging.value = false;
  dragCounter.value = 0;

  if (!portalInfo.value?.file_upload_enabled || visibleInputFields.value.length === 0) return;

  const file = e.dataTransfer?.files[0];
  if (!file) return;

  const targetField = fieldKey || visibleInputFields.value[0]?.key;
  if (!targetField) return;

  await processFile(file, targetField);
}

function handleFieldDragEnter(e: DragEvent, fieldKey: string): void {
  if (!portalInfo.value?.file_upload_enabled) return;
  if (!e.dataTransfer?.types.includes("Files")) return;
  if (!fieldDragCounters.value[fieldKey]) {
    fieldDragCounters.value[fieldKey] = 0;
  }
  fieldDragCounters.value[fieldKey]++;
  dragTargetField.value = fieldKey;
}

function handleFieldDragLeave(_e: DragEvent, fieldKey: string): void {
  if (!portalInfo.value?.file_upload_enabled) return;
  if (!fieldDragCounters.value[fieldKey]) return;
  fieldDragCounters.value[fieldKey]--;
  if (fieldDragCounters.value[fieldKey] === 0) {
    if (dragTargetField.value === fieldKey) {
      dragTargetField.value = null;
    }
  }
}

async function handleFieldDrop(e: DragEvent, fieldKey: string): Promise<void> {
  dragTargetField.value = null;
  fieldDragCounters.value[fieldKey] = 0;

  if (!portalInfo.value?.file_upload_enabled) return;

  const file = e.dataTransfer?.files[0];
  if (!file) return;

  await processFile(file, fieldKey);
}

async function handleSubmit(): Promise<void> {
  if (isExecuting.value) return;

  const userMessage: ChatMessage = {
    id: crypto.randomUUID(),
    type: "user",
    content: formatUserMessage(),
    timestamp: new Date(),
  };
  messages.value.push(userMessage);
  scrollToBottom();

  const inputsToSend = { ...inputValues.value };
  clearInputs();

  isExecuting.value = true;
  currentProgress.value = [];
  stopRequested.value = false;
  activeExecutionId.value = null;
  const startTime = performance.now();
  const abortController = new AbortController();
  activeAbortController.value = abortController;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...heymClientHeaders,
  };
  const token = localStorage.getItem(getSessionTokenKey()) || sessionToken.value;
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
    sessionToken.value = token;
  }

  try {
    await executeStream(
      headers,
      startTime,
      inputsToSend,
      abortController.signal,
      portalInfo.value?.stream_enabled === true,
    );
    notifyResponse();
  } catch (error: unknown) {
    if (stopRequested.value) {
      return;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      return;
    }
    messages.value.push({
      id: crypto.randomUUID(),
      type: "system",
      content: "Execution failed. Please try again.",
      timestamp: new Date(),
    });
  } finally {
    isExecuting.value = false;
    currentProgress.value = [];
    activeAbortController.value = null;
    activeExecutionId.value = null;
    stopRequested.value = false;
  }
}

function formatUserMessage(): string {
  const parts: string[] = [];
  const hasMultipleFields = visibleInputFields.value.length > 1;

  for (const field of visibleInputFields.value) {
    const value = inputValues.value[field.key];
    if (value) {
      if (uploadedFiles.value[field.key]) {
        if (hasMultipleFields) {
          parts.push(`${field.key}: [${uploadedFiles.value[field.key].name}]`);
        } else {
          parts.push(`[${uploadedFiles.value[field.key].name}]`);
        }
      } else {
        if (hasMultipleFields) {
          parts.push(`${field.key}: ${value.substring(0, 100)}${value.length > 100 ? "..." : ""}`);
        } else {
          parts.push(value);
        }
      }
    }
  }
  return parts.join("\n") || "Requested";
}

async function executeStream(
  headers: Record<string, string>,
  startTime: number,
  inputsToSend: Record<string, string>,
  signal: AbortSignal,
  showProgress: boolean,
): Promise<void> {
  const response = await fetch(`${API_URL}/api/portal/${slug.value}/execute/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      inputs: inputsToSend,
      conversation_history: conversationHistory.value,
    }),
    signal,
  });

  if (!response.ok) {
    if (response.status === 401) {
      sessionToken.value = null;
      localStorage.removeItem(getSessionTokenKey());
      throw new Error("Session expired. Please log in again.");
    }
    const data = await response.json();
    throw new Error(data.detail || "Execution failed");
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";
  let progressPath: string[] = [];
  let finalOutputDisplayed = false;

  let done = false;
  while (!done) {
    const result = await reader.read();
    done = result.done;
    if (done) break;
    const value = result.value;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = JSON.parse(line.slice(6));

        if (data.type === "execution_started" && typeof data.execution_id === "string") {
          activeExecutionId.value = data.execution_id;
        } else if (data.type === "node_start") {
          const node = data.node_label || data.node_id;
          if (isStringArray(data.progress_path) && data.progress_path.length > 0) {
            progressPath = [...data.progress_path];
          } else if (typeof node === "string") {
            progressPath = [...progressPath, node];
          }
          if (showProgress) {
            currentProgress.value = [...progressPath];
          }
        } else if (data.type === "final_output" && !finalOutputDisplayed) {
          const savedProgress = [...progressPath];
          const unwrappedJsonMapper =
            data.node_type === "jsonOutputMapper"
            && data.output !== null
            && typeof data.output === "object"
            && !Array.isArray(data.output);
          const outputsForDisplay: Record<string, unknown> = unwrappedJsonMapper
            ? (data.output as Record<string, unknown>)
            : { [data.node_label]: data.output };
          const outputContent = formatOutput(outputsForDisplay);
          const outputImages = extractImages(outputsForDisplay, data.node_results || []);
          const duration = (performance.now() - startTime) / 1000;
          messages.value.push({
            id: crypto.randomUUID(),
            type: "assistant",
            content: outputContent,
            timestamp: new Date(),
            images: outputImages.length > 0 ? outputImages : undefined,
            nodeProgress: savedProgress,
            duration,
          });
          finalOutputDisplayed = true;
        } else if (data.type === "execution_complete") {
          const savedProgress = [...progressPath];
          currentProgress.value = [];
          if (!finalOutputDisplayed) {
            const outputContent = formatOutput(data.outputs);
            const outputImages = extractImages(data.outputs || {}, data.node_results);
            const duration = (performance.now() - startTime) / 1000;
            messages.value.push({
              id: crypto.randomUUID(),
              type: "assistant",
              content: outputContent,
              timestamp: new Date(),
              images: outputImages.length > 0 ? outputImages : undefined,
              nodeProgress: savedProgress,
              duration,
            });
          }
        }
      }
    }
  }
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

async function stopExecution(): Promise<void> {
  if (!isExecuting.value) return;

  stopRequested.value = true;
  currentProgress.value = [];
  isExecuting.value = false;

  const token = localStorage.getItem(getSessionTokenKey()) || sessionToken.value;
  const executionId = activeExecutionId.value;

  try {
    if (executionId) {
      const headers: Record<string, string> = {
        ...heymClientHeaders,
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      await fetch(`${API_URL}/api/portal/${slug.value}/executions/${executionId}/cancel`, {
        method: "POST",
        headers,
      });
    }
  } catch {
    // Ignore cancel endpoint failures; aborting the stream still disconnects the run.
  } finally {
    activeAbortController.value?.abort();
    activeAbortController.value = null;
    activeExecutionId.value = null;
  }

  messages.value.push({
    id: crypto.randomUUID(),
    type: "system",
    content: "Execution stopped.",
    timestamp: new Date(),
  });
  focusChatInput();
}

function formatOutput(outputs: Record<string, unknown>): string {
  if (!outputs || Object.keys(outputs).length === 0) {
    return "No output";
  }

  const parts: string[] = [];
  for (const [, value] of Object.entries(outputs)) {
    if (typeof value === "object" && value !== null) {
      const obj = value as Record<string, unknown>;
      if (
        obj.decision === null &&
        typeof obj.reviewUrl === "string" &&
        typeof obj.draftText === "string"
      ) {
        const summary = typeof obj.summary === "string" ? cleanString(obj.summary) : "";
        const draftText = cleanString(obj.draftText);
        const preview = draftText.length > 240 ? `${draftText.slice(0, 240)}...` : draftText;
        parts.push(
          [
            "Human review is required before this workflow can continue.",
            summary,
            preview,
            `[Open review page](${obj.reviewUrl})`,
          ]
            .filter(Boolean)
            .join("\n\n")
        );
        continue;
      }
      if (typeof obj.text === "string" && obj.text) {
        const cleanedText = cleanString(obj.text);
        if (cleanedText) {
          parts.push(cleanedText);
        }
      } else if (obj.result !== undefined) {
        if (typeof obj.result === "string") {
          const cleanedResult = cleanString(obj.result);
          if (cleanedResult) {
            parts.push(cleanedResult);
          }
        } else {
          parts.push(JSON.stringify(obj.result, null, 2));
        }
      } else if (!hasImageOutput(obj)) {
        parts.push(JSON.stringify(value, null, 2));
      }
    } else {
      const cleanedValue = cleanString(String(value));
      if (cleanedValue) {
        parts.push(cleanedValue);
      }
    }
  }
  const joined = parts.join("\n\n");
  const finalResult = cleanString(joined);
  return finalResult;
}

function hasImageOutput(obj: Record<string, unknown>): boolean {
  if (typeof obj.image === "string" && obj.image.startsWith("data:image")) return true;
  if (typeof obj.screenshot === "string" && obj.screenshot.length > 100) return true;
  if (obj.results && typeof obj.results === "object") {
    for (const v of Object.values(obj.results as Record<string, unknown>)) {
      if (typeof v === "string" && v.length > 100 && /^[A-Za-z0-9+/=]+$/.test(v)) return true;
    }
  }
  return false;
}

function extractImagesFromObject(obj: Record<string, unknown>): string[] {
  const images: string[] = [];
  if (typeof obj.image === "string" && obj.image.startsWith("data:image")) {
    images.push(obj.image);
  }
  if (typeof obj.screenshot === "string" && obj.screenshot.length > 100) {
    images.push(`data:image/png;base64,${obj.screenshot}`);
  }
  if (obj.results && typeof obj.results === "object") {
    for (const v of Object.values(obj.results as Record<string, unknown>)) {
      if (typeof v === "string" && v.length > 100 && /^[A-Za-z0-9+/=]+$/.test(v)) {
        images.push(`data:image/png;base64,${v}`);
      }
    }
  }
  return images;
}

function extractImages(
  outputs: Record<string, unknown>,
  nodeResults?: Array<{ output?: unknown }>,
): string[] {
  const seen = new Set<string>();
  const images: string[] = [];
  for (const [, value] of Object.entries(outputs)) {
    if (typeof value === "object" && value !== null) {
      for (const img of extractImagesFromObject(value as Record<string, unknown>)) {
        if (!seen.has(img)) {
          seen.add(img);
          images.push(img);
        }
      }
    }
  }
  if (nodeResults) {
    for (const r of nodeResults) {
      const out = r.output;
      if (typeof out === "object" && out !== null) {
        for (const img of extractImagesFromObject(out as Record<string, unknown>)) {
          if (!seen.has(img)) {
            seen.add(img);
            images.push(img);
          }
        }
      }
    }
  }
  return images;
}

function cleanString(str: string): string {
  if (!str || str.trim() === "") {
    return "";
  }

  let cleaned = str.trim();

  if (cleaned === '""' || cleaned === "''" || cleaned === '"' || cleaned === "'") {
    return "";
  }

  cleaned = cleaned.replace(/\\"/g, '"').replace(/\\'/g, "'");

  let loopCount = 0;
  while (cleaned.length >= 2 && loopCount < 10) {
    loopCount++;
    const startsWithQuote = cleaned.startsWith('"');
    const endsWithQuote = cleaned.endsWith('"');
    const startsWithSingleQuote = cleaned.startsWith("'");
    const endsWithSingleQuote = cleaned.endsWith("'");

    if (startsWithQuote && endsWithQuote) {
      try {
        const parsed = JSON.parse(cleaned);
        if (typeof parsed === "string") {
          cleaned = parsed;
          continue;
        }
      } catch {
        // JSON.parse failed, fallback to manual quote removal
      }
      cleaned = cleaned.slice(1, -1);
    } else if (startsWithSingleQuote && endsWithSingleQuote) {
      cleaned = cleaned.slice(1, -1);
    } else if (endsWithQuote && !startsWithQuote) {
      cleaned = cleaned.slice(0, -1);
    } else if (startsWithQuote && !endsWithQuote) {
      cleaned = cleaned.slice(1);
    } else {
      break;
    }
  }

  cleaned = cleaned.replace(/^##\s*"([^"]+)"\s*$/gm, '## $1');
  cleaned = cleaned.replace(/^###\s*"([^"]+)"\s*$/gm, '### $1');
  cleaned = cleaned.replace(/^####\s*"([^"]+)"\s*$/gm, '#### $1');
  cleaned = cleaned.replace(/^#\s*"([^"]+)"\s*$/gm, '# $1');
  cleaned = cleaned.replace(/^"([^"]+)"\s*$/gm, '$1');

  const lines = cleaned.split("\n");
  const cleanedLines = lines.map((line) => {
    const trimmed = line.trim();
    if (trimmed.startsWith('"') && trimmed.endsWith('"') && trimmed.length >= 2) {
      try {
        const parsed = JSON.parse(trimmed);
        if (typeof parsed === "string") {
          return parsed;
        }
      } catch {
        // JSON.parse failed, fallback to manual quote removal
      }
      return trimmed.slice(1, -1);
    }
    if (trimmed.startsWith("'") && trimmed.endsWith("'") && trimmed.length >= 2) {
      return trimmed.slice(1, -1);
    }
    if (trimmed.endsWith('"') && !trimmed.startsWith('"')) {
      return trimmed.slice(0, -1);
    }
    if (trimmed.startsWith('"') && !trimmed.endsWith('"')) {
      return trimmed.slice(1);
    }
    return line;
  });

  return cleanedLines.join("\n");
}

function clearInputs(): void {
  for (const field of portalInfo.value?.input_fields || []) {
    inputValues.value[field.key] = field.defaultValue || "";
    delete uploadedFiles.value[field.key];
  }
  resetTextareaHeight();
}

const singleInputTextarea = ref<HTMLTextAreaElement | null>(null);

function focusChatInput(): void {
  nextTick(() => {
    nextTick(() => {
      if (visibleInputFields.value.length === 1 && singleInputTextarea.value) {
        singleInputTextarea.value.focus();
      } else if (visibleInputFields.value.length > 0) {
        const firstField = visibleInputFields.value[0];
        document.getElementById(`field-${firstField.key}`)?.focus();
      }
    });
  });
}

function autoResize(event: Event): void {
  const textarea = event.target as HTMLTextAreaElement;
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 240) + "px";
}

function resizeTextarea(fieldKey?: string): void {
  if (singleInputTextarea.value && !fieldKey) {
    singleInputTextarea.value.style.height = "auto";
    singleInputTextarea.value.style.height = Math.min(singleInputTextarea.value.scrollHeight, 240) + "px";
  }
  if (fieldKey) {
    const textarea = document.getElementById(`field-${fieldKey}`) as HTMLTextAreaElement | null;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = Math.min(textarea.scrollHeight, 240) + "px";
    }
  }
}

function resetTextareaHeight(): void {
  if (singleInputTextarea.value) {
    singleInputTextarea.value.style.height = "auto";
  }
  for (const field of visibleInputFields.value) {
    const textarea = document.getElementById(`field-${field.key}`) as HTMLTextAreaElement | null;
    if (textarea) {
      textarea.style.height = "auto";
    }
  }
}

function renderMarkdown(content: string): string {
  if (!content) return "";
  const html = marked(content, {
    breaks: true,
    gfm: true,
  }) as string;
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

function handleMarkdownImageClick(event: MouseEvent): void {
  const target = event.target as HTMLElement;
  if (target.tagName === "IMG") {
    const img = target as HTMLImageElement;
    imageLightboxSrc.value = img.src;
  }
}

function extractPlainText(html: string): string {
  const tempDiv = document.createElement("div");
  tempDiv.innerHTML = html;
  return tempDiv.textContent || tempDiv.innerText || "";
}

async function copyMessage(message: ChatMessage): Promise<void> {
  try {
    let textToCopy = message.content;
    if (message.type === "assistant") {
      const html = renderMarkdown(message.content);
      textToCopy = extractPlainText(html);
    }
    await navigator.clipboard.writeText(textToCopy);
    copiedMessageId.value = message.id;
    setTimeout(() => {
      copiedMessageId.value = null;
    }, 2000);
  } catch {
    // Silently ignore clipboard errors (e.g., permission denied)
  }
}

function downloadAsHTML(): void {
  if (!portalInfo.value) return;

  const workflowName = portalInfo.value.workflow_name;
  const workflowDesc = portalInfo.value.workflow_description || "";

  const messageElements = messages.value
    .filter(m => m.type === "user" || m.type === "assistant")
    .map((m, i) => {
      const isUser = m.type === "user";
      const contentHtml = isUser
        ? `<p style="white-space:pre-wrap;margin:0;">${escapeHtml(m.content)}</p>`
        : renderMarkdown(m.content);

      const imagesHtml = (m.images || [])
        .map(src => `<img src="${src}" alt="Generated image" style="max-height:16rem;max-width:100%;border-radius:0.5rem;margin-top:0.5em;" />`)
        .join("");

      const progressHtml = m.nodeProgress && m.nodeProgress.length > 0
        ? `<p style="font-size:0.75rem;opacity:0.7;margin-top:0.5em;border-top:1px solid rgba(0,0,0,0.1);padding-top:0.5em;">Nodes: ${escapeHtml(m.nodeProgress.join(" \u2192 "))}</p>`
        : "";

      const durationHtml = !isUser && m.duration !== undefined
        ? `<p style="font-size:0.75rem;opacity:0.5;margin-top:0.25em;">${m.duration.toFixed(2)}s</p>`
        : "";

      const handleHtml = isUser
        ? `<div class="resize-handle resize-handle-left" onmousedown="startResize(event,this.parentElement,'left')"></div>`
        : `<div class="resize-handle resize-handle-right" onmousedown="startResize(event,this.parentElement,'right')"></div>`;

      const copyBtn = `<button class="copy-btn" onclick="copyMsg(this)" data-index="${i}">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
      </button>`;

      const bubbleClass = isUser ? "bubble user-bubble" : "bubble assistant-bubble";
      const alignClass = isUser ? "msg-row msg-right" : "msg-row msg-left";

      return `<div class="${alignClass}"><div class="${bubbleClass}">${handleHtml}<div class="bubble-content">${contentHtml}${imagesHtml}${progressHtml}${durationHtml}</div>${copyBtn}</div></div>`;
    })
    .join("\n");

  const plainTexts = messages.value
    .filter(m => m.type === "user" || m.type === "assistant")
    .map(m => m.content);

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(workflowName)} - Chat Export</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;transition:background .3s,color .3s}
  body.light{background:#f8f9fa;color:#1a1a1a}
  body.dark{background:#0a0a1a;color:#e5e7eb}
  .header{border-bottom:1px solid;padding:1rem;display:flex;align-items:center;justify-content:center;position:sticky;top:0;z-index:10;transition:background .3s,border-color .3s}
  .light .header{background:#fff;border-color:#e5e7eb}
  .dark .header{background:#111127;border-color:#2d2d44}
  .header-inner{max-width:48rem;width:100%;display:flex;align-items:center;justify-content:space-between}
  .header-info{text-align:left}
  .header h1{font-size:1.125rem;font-weight:600}
  .header p{font-size:0.875rem;margin-top:0.25rem}
  .light .header p{color:#6b7280}
  .dark .header p{color:#9ca3af}
  .theme-btn{width:40px;height:40px;border-radius:0.75rem;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s}
  .light .theme-btn{background:#f3f4f6;color:#6b7280}
  .light .theme-btn:hover{background:#e8e5ff;color:#7c3aed}
  .dark .theme-btn{background:#1e1e38;color:#9ca3af}
  .dark .theme-btn:hover{background:#2a1e4e;color:#a78bfa}
  .messages{max-width:48rem;margin:0 auto;padding:1.5rem 1rem}
  .msg-row{display:flex;margin-bottom:1rem}
  .msg-right{justify-content:flex-end}
  .msg-left{justify-content:flex-start}
  .bubble{border-radius:1rem;padding:0.75rem 1rem;max-width:75%;position:relative;transition:background .3s,border-color .3s,box-shadow .3s}
  .user-bubble{background:linear-gradient(135deg,#7c3aed,#9333ea);color:#fff;box-shadow:0 2px 8px rgba(124,58,237,0.3)}
  .light .assistant-bubble{background:#fff;border:1px solid #e5e7eb;box-shadow:0 2px 8px rgba(0,0,0,0.06)}
  .dark .assistant-bubble{background:#161630;border:1px solid #2d2d44;box-shadow:0 2px 8px rgba(0,0,0,0.3)}
  .bubble-content{position:relative;z-index:1}
  .copy-btn{position:absolute;bottom:0.5rem;right:0.5rem;width:32px;height:32px;border-radius:0.5rem;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .2s,background .2s;z-index:2}
  .bubble:hover .copy-btn{opacity:1}
  .user-bubble .copy-btn{background:rgba(255,255,255,0.2);color:#fff}
  .user-bubble .copy-btn:hover{background:rgba(255,255,255,0.3)}
  .light .assistant-bubble .copy-btn{background:#f3f4f6;color:#6b7280}
  .light .assistant-bubble .copy-btn:hover{background:#e5e7eb}
  .dark .assistant-bubble .copy-btn{background:#1e1e38;color:#9ca3af}
  .dark .assistant-bubble .copy-btn:hover{background:#2d2d44}
  .resize-handle{position:absolute;top:0;bottom:0;width:6px;cursor:col-resize;opacity:0;transition:opacity .2s;z-index:5}
  .resize-handle::after{content:'';position:absolute;top:50%;transform:translateY(-50%);width:2px;height:24px;border-radius:1px;background:rgba(124,58,237,0.5)}
  .bubble:hover .resize-handle{opacity:1}
  .resize-handle-left{left:-3px}
  .resize-handle-left::after{left:2px}
  .resize-handle-right{right:-3px}
  .resize-handle-right::after{right:2px}
  table{width:100%;border-collapse:collapse;margin:0.75em 0}
  .light th,.light td{border:1px solid #e5e7eb;padding:0.5em;text-align:left}
  .dark th,.dark td{border:1px solid #2d2d44;padding:0.5em;text-align:left}
  .light th{background:#f3f4f6;font-weight:600}
  .dark th{background:#1e1e38;font-weight:600}
  pre{padding:0.75em;border-radius:0.5rem;overflow-x:auto;margin:0.75em 0}
  .light pre{background:#f3f4f6}
  .dark pre{background:#1e1e38}
  code{padding:0.125em 0.375em;border-radius:0.25rem;font-size:0.875em}
  .light code{background:#f3f4f6}
  .dark code{background:#1e1e38}
  pre code{background:transparent;padding:0}
  blockquote{border-left:3px solid rgba(124,58,237,0.2);padding-left:1em;margin:0.75em 0;opacity:0.8}
  a{color:#7c3aed}
  h1,h2,h3,h4,h5,h6{font-weight:600;margin-top:1em;margin-bottom:0.5em}
  ul,ol{padding-left:1.5em;margin:0.5em 0}
  img{max-width:100%}
  .footer{text-align:center;padding:2rem 1rem;font-size:0.75rem}
  .light .footer{color:#9ca3af}
  .dark .footer{color:#4b5563}
</style>
</head>
<body class="light">
<div class="header">
  <div class="header-inner">
    <div class="header-info">
      <h1>${escapeHtml(workflowName)}</h1>
      ${workflowDesc ? `<p>${escapeHtml(workflowDesc)}</p>` : ""}
    </div>
    <button class="theme-btn" onclick="toggleTheme()" title="Toggle theme">
      <svg id="icon-sun" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:none"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      <svg id="icon-moon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
    </button>
  </div>
</div>
<div class="messages">
  ${messageElements}
</div>
<div class="footer">
  Exported on ${new Date().toLocaleString()}
</div>
<script>
var msgTexts=${JSON.stringify(plainTexts)};
function toggleTheme(){
  var b=document.body;
  var isDark=b.classList.contains('dark');
  b.classList.remove(isDark?'dark':'light');
  b.classList.add(isDark?'light':'dark');
  document.getElementById('icon-sun').style.display=isDark?'none':'block';
  document.getElementById('icon-moon').style.display=isDark?'block':'none';
}
function copyMsg(btn){
  var idx=parseInt(btn.getAttribute('data-index'));
  var text=msgTexts[idx]||'';
  navigator.clipboard.writeText(text).then(function(){
    btn.innerHTML='<span style="font-size:0.7rem">Copied</span>';
    setTimeout(function(){btn.innerHTML='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';},1500);
  });
}
function startResize(e,bubble,dir){
  e.preventDefault();e.stopPropagation();
  var startX=e.touches?e.touches[0].clientX:e.clientX;
  var startW=bubble.offsetWidth;
  var container=document.querySelector('.messages');
  var maxW=container?container.clientWidth*0.95:800;
  var minW=200;
  document.body.style.userSelect='none';
  document.body.style.cursor='col-resize';
  function onMove(ev){
    var cx=ev.touches?ev.touches[0].clientX:ev.clientX;
    var dx=cx-startX;
    var nw=dir==='left'?startW-dx:startW+dx;
    nw=Math.max(minW,Math.min(maxW,nw));
    bubble.style.maxWidth=nw+'px';
  }
  function onEnd(){
    document.body.style.userSelect='';
    document.body.style.cursor='';
    document.removeEventListener('mousemove',onMove);
    document.removeEventListener('mouseup',onEnd);
    document.removeEventListener('touchmove',onMove);
    document.removeEventListener('touchend',onEnd);
  }
  document.addEventListener('mousemove',onMove);
  document.addEventListener('mouseup',onEnd);
  document.addEventListener('touchmove',onMove,{passive:false});
  document.addEventListener('touchend',onEnd);
}
</${"script"}>
</body>
</html>`;

  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const now = new Date();
  const timestamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}-${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
  a.href = url;
  a.download = `${workflowName.replace(/[^a-zA-Z0-9]/g, "-")}-chat-${timestamp}.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function handleMessageClick(messageId: string): void {
  if (activeMessageId.value === messageId) {
    activeMessageId.value = null;
  } else {
    activeMessageId.value = messageId;
  }
}

function handleClickOutside(event: MouseEvent): void {
  const target = event.target as HTMLElement;
  if (!target.closest(".message-bubble")) {
    activeMessageId.value = null;
  }
}

function startResize(event: MouseEvent | TouchEvent, messageId: string, direction: "left" | "right"): void {
  event.preventDefault();
  event.stopPropagation();

  const clientX = "touches" in event ? event.touches[0].clientX : event.clientX;
  const bubble = (event.target as HTMLElement).closest(".message-bubble") as HTMLElement;
  if (!bubble) return;

  const startX = clientX;
  const startWidth = bubble.offsetWidth;
  const container = messagesContainer.value;
  const maxWidth = container ? container.clientWidth * 0.95 : 800;
  const minWidth = 200;

  isDraggingResize.value = true;
  document.body.style.userSelect = "none";
  document.body.style.cursor = "col-resize";

  function onMove(e: MouseEvent | TouchEvent): void {
    const currentX = "touches" in e ? e.touches[0].clientX : e.clientX;
    const deltaX = currentX - startX;
    let newWidth: number;

    if (direction === "left") {
      newWidth = startWidth - deltaX;
    } else {
      newWidth = startWidth + deltaX;
    }

    newWidth = Math.max(minWidth, Math.min(maxWidth, newWidth));
    messageWidths.value[messageId] = newWidth;
  }

  function onEnd(): void {
    isDraggingResize.value = false;
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onEnd);
    document.removeEventListener("touchmove", onMove);
    document.removeEventListener("touchend", onEnd);
  }

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onEnd);
  document.addEventListener("touchmove", onMove, { passive: false });
  document.addEventListener("touchend", onEnd);
}
</script>

<template>
  <div class="portal-container h-screen flex flex-col overflow-hidden overflow-x-hidden relative">
    <!-- Workflow graph background only while portal login screen is visible -->
    <WorkflowHeroBackground
      v-if="portalInfo && portalInfo.requires_auth && !isAuthenticated"
    />

    <div class="relative z-10 h-full flex flex-col">
      <div
        v-if="isLoading"
        class="flex-1 flex items-center justify-center"
      >
        <div class="flex flex-col items-center gap-4">
          <div class="loading-spinner w-12 h-12 rounded-full animate-spin" />
          <span class="text-muted-foreground text-sm">Loading portal...</span>
        </div>
      </div>

      <div
        v-else-if="error"
        class="flex-1 flex items-center justify-center"
      >
        <div class="text-center space-y-4">
          <div class="error-icon w-16 h-16 rounded-2xl flex items-center justify-center mx-auto">
            <AlertCircle class="w-8 h-8 text-destructive" />
          </div>
          <p class="text-lg text-muted-foreground">
            {{ error }}
          </p>
        </div>
      </div>

      <div
        v-else-if="portalInfo"
        class="flex-1 flex flex-col min-h-0"
      >
        <header class="portal-header border-b border-border/30 sticky top-0 z-10">
          <div class="max-w-3xl mx-auto px-4 py-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="header-icon w-10 h-10 rounded-xl flex items-center justify-center">
                <Workflow class="w-5 h-5 text-primary" />
              </div>
              <div>
                <h1 class="text-lg font-semibold">
                  {{ portalInfo.workflow_name }}
                </h1>
                <p
                  v-if="portalInfo.workflow_description"
                  class="text-sm text-muted-foreground line-clamp-1"
                >
                  {{ portalInfo.workflow_description }}
                </p>
              </div>
            </div>
            <div class="flex items-center gap-1">
              <button
                v-if="hasResponses"
                type="button"
                class="theme-toggle p-2.5 rounded-xl transition-all min-h-[44px] min-w-[44px] flex items-center justify-center"
                @click="downloadAsHTML"
              >
                <Download class="w-5 h-5" />
              </button>
              <button
                type="button"
                class="theme-toggle p-2.5 rounded-xl transition-all min-h-[44px] min-w-[44px] flex items-center justify-center"
                @click="themeStore.toggle()"
              >
                <Sun
                  v-if="themeStore.isDark"
                  class="w-5 h-5"
                />
                <Moon
                  v-else
                  class="w-5 h-5"
                />
              </button>
            </div>
          </div>
        </header>

        <div
          v-if="portalInfo.requires_auth && !isAuthenticated"
          class="flex-1 flex items-center justify-center p-4"
        >
          <div class="auth-card w-full max-w-sm p-8 rounded-2xl">
            <div class="text-center mb-8">
              <img
                src="/fav.svg"
                alt="Heym"
                class="w-16 h-16 mx-auto mb-4"
              >
              <h2 class="text-xl font-semibold">
                Authentication Required
              </h2>
              <p class="text-sm text-muted-foreground mt-2">
                Please log in to access this workflow
              </p>
            </div>

            <form
              class="space-y-4"
              @submit.prevent="handleLogin"
            >
              <div class="space-y-2">
                <Label for="username">Username</Label>
                <Input
                  id="username"
                  v-model="username"
                  placeholder="Enter username"
                  autocomplete="username"
                />
              </div>
              <div class="space-y-2">
                <Label for="password">Password</Label>
                <div class="relative">
                  <Input
                    id="password"
                    v-model="password"
                    :type="showPassword ? 'text' : 'password'"
                    placeholder="Enter password"
                    autocomplete="current-password"
                    class="pr-10"
                  />
                  <button
                    type="button"
                    class="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-muted-foreground hover:text-foreground transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
                    @click="showPassword = !showPassword"
                  >
                    <Eye
                      v-if="!showPassword"
                      class="w-4 h-4"
                    />
                    <EyeOff
                      v-else
                      class="w-4 h-4"
                    />
                  </button>
                </div>
              </div>

              <p
                v-if="loginError"
                class="text-sm text-destructive"
              >
                {{ loginError }}
              </p>

              <Button
                type="submit"
                variant="gradient"
                class="w-full mt-6 min-h-[44px]"
                :loading="isLoggingIn"
                :disabled="!username.trim() || !password"
              >
                Sign In
              </Button>
            </form>
          </div>
        </div>

        <template v-else>
          <div
            v-if="portalInfo.file_upload_enabled && isDragging && visibleInputFields.length === 1"
            class="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center"
            @dragenter="handleDragEnter"
            @dragleave="handleDragLeave"
            @dragover="handleDragOver"
            @drop="handleDrop($event)"
          >
            <div class="drop-zone border-2 border-dashed border-primary rounded-2xl p-12 text-center">
              <div class="drop-icon w-16 h-16 mx-auto rounded-2xl flex items-center justify-center mb-4">
                <Upload class="w-8 h-8 text-primary" />
              </div>
              <p class="text-lg font-medium">
                Drop file here
              </p>
              <p class="text-sm text-muted-foreground mt-1">
                Release to upload
              </p>
            </div>
          </div>
          <main
            ref="messagesContainer"
            class="flex-1 overflow-y-auto messages-area"
            @dragenter="handleDragEnter"
            @dragleave="handleDragLeave"
            @dragover="handleDragOver"
            @drop="handleDrop($event)"
          >
            <div class="max-w-3xl mx-auto px-4 py-6 space-y-4">
              <div
                v-if="messages.length === 0"
                class="empty-state text-center py-16"
              >
                <div class="empty-icon w-16 h-16 mx-auto rounded-2xl flex items-center justify-center mb-4">
                  <Send class="w-8 h-8 text-muted-foreground" />
                </div>
                <p class="text-muted-foreground">
                  Send a message to get started
                </p>
              </div>
              <div
                v-for="message in messages"
                :key="message.id"
                class="flex animate-slide-up"
                :class="message.type === 'user' ? 'justify-end' : 'justify-start'"
              >
                <div
                  class="message-bubble max-w-[85%] sm:max-w-[75%] rounded-2xl px-4 py-3 relative group"
                  :class="{
                    'user-bubble': message.type === 'user',
                    'assistant-bubble': message.type === 'assistant',
                    'system-bubble': message.type === 'system',
                  }"
                  :style="messageWidths[message.id] ? { maxWidth: messageWidths[message.id] + 'px' } : undefined"
                  @click.stop="handleMessageClick(message.id)"
                >
                  <!-- Left resize handle for user messages -->
                  <div
                    v-if="message.type === 'user'"
                    class="resize-handle resize-handle-left"
                    @mousedown="startResize($event, message.id, 'left')"
                    @touchstart="startResize($event, message.id, 'left')"
                  />
                  <!-- Right resize handle for assistant messages -->
                  <div
                    v-if="message.type === 'assistant'"
                    class="resize-handle resize-handle-right"
                    @mousedown="startResize($event, message.id, 'right')"
                    @touchstart="startResize($event, message.id, 'right')"
                  />
                  <!-- eslint-disable-next-line vue/no-v-html -->
                  <div
                    v-if="message.type === 'assistant'"
                    class="markdown-content text-sm break-words overflow-wrap-anywhere"
                    @click="handleMarkdownImageClick"
                    v-html="renderMarkdown(message.content)"
                  />
                  <p
                    v-else
                    class="text-sm whitespace-pre-wrap break-words overflow-wrap-anywhere"
                  >
                    {{ message.content }}
                  </p>
                  <div
                    v-if="message.images && message.images.length > 0"
                    class="mt-2 flex flex-wrap gap-2"
                  >
                    <img
                      v-for="(imgSrc, idx) in message.images"
                      :key="idx"
                      :src="imgSrc"
                      alt="Generated image"
                      class="max-h-64 max-w-full rounded-lg object-contain cursor-zoom-in border border-white/10 hover:border-white/30 transition-colors"
                      @click.stop="imageLightboxSrc = imgSrc"
                    >
                  </div>
                  <div
                    v-if="message.nodeProgress && message.nodeProgress.length > 0"
                    class="mt-2 pt-2 border-t border-current/10"
                  >
                    <p class="text-xs opacity-70">
                      Nodes: {{ message.nodeProgress.join(" → ") }}
                    </p>
                  </div>
                  <p
                    v-if="message.type === 'assistant' && message.duration !== undefined"
                    class="text-xs opacity-50 mt-1"
                  >
                    {{ message.duration.toFixed(2) }}s
                  </p>
                  <button
                    v-if="message.type === 'user' || message.type === 'assistant'"
                    type="button"
                    class="absolute bottom-2 right-2 p-2 rounded-lg transition-opacity min-h-[44px] min-w-[44px] flex items-center justify-center"
                    :class="{
                      'bg-white/20 hover:bg-white/30': message.type === 'user',
                      'bg-muted/80 hover:bg-muted': message.type === 'assistant',
                      'opacity-100': activeMessageId === message.id || copiedMessageId === message.id,
                      'opacity-0 md:group-hover:opacity-100': activeMessageId !== message.id && copiedMessageId !== message.id,
                    }"
                    @click.stop="copyMessage(message)"
                  >
                    <Copy
                      v-if="copiedMessageId !== message.id"
                      class="w-3.5 h-3.5"
                      :class="{
                        'text-white': message.type === 'user',
                        'text-muted-foreground': message.type === 'assistant',
                      }"
                    />
                    <span
                      v-else
                      class="text-xs"
                      :class="{
                        'text-white': message.type === 'user',
                        'text-primary': message.type === 'assistant',
                      }"
                    >
                      Copied
                    </span>
                  </button>
                </div>
              </div>

              <div
                v-if="isExecuting && currentProgress.length > 0"
                class="flex justify-start animate-slide-up"
              >
                <div class="message-bubble assistant-bubble rounded-2xl px-4 py-3">
                  <div class="flex items-center gap-2">
                    <Loader2 class="w-4 h-4 animate-spin text-primary" />
                    <Transition
                      name="text-fade"
                      mode="out-in"
                    >
                      <span
                        :key="currentProgress[currentProgress.length - 1]"
                        class="text-sm"
                      >
                        {{ currentProgress[currentProgress.length - 1] }}
                      </span>
                    </Transition>
                  </div>
                  <p class="text-xs text-muted-foreground mt-1 progress-text">
                    {{ currentProgress.join(" → ") }}
                  </p>
                </div>
              </div>
            </div>
          </main>

          <footer class="portal-footer border-t border-border/30 sticky bottom-0 shrink-0 pb-[env(safe-area-inset-bottom,0px)]">
            <div class="max-w-3xl mx-auto px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
              <form @submit.prevent="handleSubmit">
                <template v-if="visibleInputFields.length === 1">
                  <div class="input-container relative flex items-end gap-2 rounded-2xl p-2 md:p-4">
                    <label
                      v-if="portalInfo.file_upload_enabled"
                      class="upload-button cursor-pointer p-2.5 rounded-xl transition-all min-h-[44px] min-w-[44px] flex items-center justify-center"
                    >
                      <input
                        type="file"
                        class="hidden"
                        :accept="portalInfo.file_config[visibleInputFields[0].key]?.allowed_types?.includes('image') ? 'image/*,.txt,.md,.json,.csv' : '.txt,.md,.json,.csv'"
                        @change="(e) => handleFileUpload(e, visibleInputFields[0].key)"
                      >
                      <Upload class="w-5 h-5 text-muted-foreground" />
                    </label>
                    <textarea
                      ref="singleInputTextarea"
                      v-model="inputValues[visibleInputFields[0].key]"
                      :placeholder="visibleInputFields[0].defaultValue || 'Type a message...'"
                      rows="1"
                      class="chat-textarea flex-1 resize-none bg-transparent border-0 focus:outline-none focus:ring-0 text-sm py-2.5 px-1 max-h-60 overflow-y-auto"
                      @input="autoResize"
                      @keydown.enter.exact.prevent="handleSubmit"
                    />
                    <Button
                      v-if="!isExecuting"
                      type="submit"
                      variant="gradient"
                      size="icon"
                      :disabled="!hasAnyInput"
                      class="shrink-0 rounded-xl h-11 w-11 min-h-[44px] min-w-[44px]"
                    >
                      <Send class="w-4 h-4" />
                    </Button>
                    <Button
                      v-else
                      type="button"
                      variant="destructive"
                      size="icon"
                      class="shrink-0 rounded-xl h-11 w-11 min-h-[44px] min-w-[44px]"
                      @click="stopExecution"
                    >
                      <Square class="w-4 h-4" />
                    </Button>
                  </div>
                </template>

                <template v-else>
                  <div class="space-y-3">
                    <div
                      v-for="field in visibleInputFields"
                      :key="field.key"
                      class="input-container relative flex items-center gap-2 rounded-2xl p-2 md:p-4 transition-all"
                      :class="{
                        'ring-2 ring-primary/50 border-primary': dragTargetField === field.key,
                      }"
                      @dragenter.prevent="handleFieldDragEnter($event, field.key)"
                      @dragleave.prevent="handleFieldDragLeave($event, field.key)"
                      @dragover.prevent
                      @drop.prevent="handleFieldDrop($event, field.key)"
                    >
                      <label
                        v-if="portalInfo.file_upload_enabled"
                        class="upload-button cursor-pointer p-2.5 rounded-xl transition-all shrink-0 min-h-[44px] min-w-[44px] flex items-center justify-center"
                      >
                        <input
                          type="file"
                          class="hidden"
                          :accept="portalInfo.file_config[field.key]?.allowed_types?.includes('image') ? 'image/*,.txt,.md,.json,.csv' : '.txt,.md,.json,.csv'"
                          @change="(e) => handleFileUpload(e, field.key)"
                        >
                        <Upload class="w-5 h-5 text-muted-foreground" />
                      </label>
                      <textarea
                        :id="`field-${field.key}`"
                        v-model="inputValues[field.key]"
                        :placeholder="field.defaultValue || `Enter ${field.key}...`"
                        rows="1"
                        class="chat-textarea flex-1 resize-none bg-transparent border-0 focus:outline-none focus:ring-0 text-sm py-2.5 px-1 max-h-60 overflow-y-auto"
                        @input="autoResize"
                      />
                    </div>

                    <div class="flex justify-center pt-2">
                      <Button
                        v-if="!isExecuting"
                        type="submit"
                        variant="gradient"
                        :disabled="!hasAnyInput"
                        class="px-12 py-2.5 min-h-[44px]"
                      >
                        <Send class="w-4 h-4 mr-2" />
                        Send
                      </Button>
                      <Button
                        v-else
                        type="button"
                        variant="destructive"
                        class="px-12 py-2.5 min-h-[44px]"
                        @click="stopExecution"
                      >
                        <Square class="w-4 h-4 mr-2" />
                        Stop
                      </Button>
                    </div>
                  </div>
                </template>
              </form>
            </div>
          </footer>
        </template>
      </div>
    </div>

    <ImageLightbox
      :src="imageLightboxSrc"
      alt="Generated image"
      @close="imageLightboxSrc = null"
    />
  </div>
</template>

<style scoped>
.portal-container {
  background: hsl(var(--background));
}

.loading-spinner {
  border: 3px solid hsl(var(--muted));
  border-top-color: hsl(var(--primary));
}

.error-icon {
  background: hsl(var(--destructive) / 0.1);
}

.portal-header {
  background: linear-gradient(180deg,
      hsl(var(--card) / 0.95) 0%,
      hsl(var(--card) / 0.85) 100%);
  backdrop-filter: blur(12px);
}

.portal-header::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg,
      transparent 0%,
      hsl(var(--primary) / 0.2) 50%,
      transparent 100%);
}

.header-icon {
  background: hsl(var(--primary) / 0.1);
}

.theme-toggle {
  background: hsl(var(--muted) / 0.5);
  color: hsl(var(--muted-foreground));
}

.theme-toggle:hover {
  background: hsl(var(--primary) / 0.1);
  color: hsl(var(--primary));
}

.auth-card {
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border) / 0.6);
  box-shadow:
    0 8px 32px hsl(var(--primary) / 0.08),
    0 4px 16px hsl(0 0% 0% / 0.04),
    0 0 0 1px hsl(var(--border) / 0.3);
  backdrop-filter: blur(12px);
}

.dark .auth-card {
  background: linear-gradient(145deg,
      hsl(var(--card)) 0%,
      hsl(224 71% 9%) 100%);
  box-shadow:
    0 8px 32px hsl(0 0% 0% / 0.4),
    0 4px 16px hsl(var(--primary) / 0.05),
    0 0 0 1px hsl(var(--border) / 0.4);
}

.drop-zone {
  background: hsl(var(--primary) / 0.05);
}

.drop-icon {
  background: hsl(var(--primary) / 0.15);
}

.messages-area {
  scroll-behavior: smooth;
}

.empty-state .empty-icon {
  background: hsl(var(--muted) / 0.5);
}

.message-bubble {
  transition: all 0.2s ease-out;
}

.user-bubble {
  background: linear-gradient(135deg,
      hsl(var(--primary)) 0%,
      hsl(270 80% 50%) 100%);
  color: white;
  box-shadow: 0 2px 8px hsl(var(--primary) / 0.3);
}

.assistant-bubble {
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border) / 0.5);
  box-shadow: 0 2px 8px hsl(0 0% 0% / 0.1);
}

.system-bubble {
  background: hsl(var(--destructive) / 0.1);
  color: hsl(var(--destructive));
  border: 1px solid hsl(var(--destructive) / 0.2);
}

.portal-footer {
  background: linear-gradient(180deg,
      hsl(var(--card) / 0.95) 0%,
      hsl(var(--card) / 0.98) 100%);
  backdrop-filter: blur(12px);
}

.input-container {
  background: hsl(var(--muted) / 0.3);
  border: 1px solid hsl(var(--border) / 0.5);
}

.input-container:focus-within {
  border-color: hsl(var(--primary) / 0.5);
  box-shadow: 0 0 0 3px hsl(var(--primary) / 0.1);
}

.upload-button {
  background: transparent;
}

.upload-button:hover {
  background: hsl(var(--muted) / 0.5);
}

.chat-textarea {
  transition: height 0.2s ease-out;
}

.text-fade-enter-active,
.text-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.text-fade-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}

.text-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.progress-text {
  transition: all 0.2s ease-out;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.overflow-wrap-anywhere {
  overflow-wrap: anywhere;
  word-break: break-word;
}

@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-slide-up {
  animation: slide-up 0.3s ease-out;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4),
.markdown-content :deep(h5),
.markdown-content :deep(h6) {
  font-weight: 600;
  margin-top: 1em;
  margin-bottom: 0.5em;
  line-height: 1.25;
}

.markdown-content :deep(h1) {
  font-size: 1.5em;
}

.markdown-content :deep(h2) {
  font-size: 1.25em;
}

.markdown-content :deep(h3) {
  font-size: 1.125em;
}

.markdown-content :deep(p) {
  margin-top: 0.5em;
  margin-bottom: 0.5em;
}

.markdown-content :deep(p:first-child) {
  margin-top: 0;
}

.markdown-content :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin-top: 0.5em;
  margin-bottom: 0.5em;
  padding-left: 1.5em;
}

.markdown-content :deep(li) {
  margin-top: 0.25em;
  margin-bottom: 0.25em;
}

.markdown-content :deep(code) {
  background: hsl(var(--muted) / 0.5);
  padding: 0.125em 0.375em;
  border-radius: 0.25rem;
  font-size: 0.875em;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
}

.markdown-content :deep(pre) {
  background: hsl(var(--muted) / 0.5);
  padding: 0.75em;
  border-radius: 0.5rem;
  overflow-x: auto;
  margin-top: 0.75em;
  margin-bottom: 0.75em;
}

.markdown-content :deep(pre code) {
  background: transparent;
  padding: 0;
}

.markdown-content :deep(blockquote) {
  border-left: 3px solid hsl(var(--primary) / 0.3);
  padding-left: 1em;
  margin-left: 0;
  margin-top: 0.75em;
  margin-bottom: 0.75em;
  opacity: 0.8;
}

.markdown-content :deep(a) {
  color: hsl(var(--primary));
  text-decoration: underline;
  text-underline-offset: 2px;
}

.markdown-content :deep(a:hover) {
  opacity: 0.8;
}

.markdown-content :deep(hr) {
  border: none;
  border-top: 1px solid hsl(var(--border) / 0.5);
  margin: 1em 0;
}

.markdown-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-top: 0.75em;
  margin-bottom: 0.75em;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid hsl(var(--border) / 0.5);
  padding: 0.5em;
  text-align: left;
}

.markdown-content :deep(th) {
  background: hsl(var(--muted) / 0.3);
  font-weight: 600;
}

.markdown-content :deep(strong) {
  font-weight: 600;
}

.markdown-content :deep(em) {
  font-style: italic;
}

.markdown-content :deep(img) {
  max-width: 100%;
  max-height: 18rem;
  border-radius: 0.5rem;
  cursor: zoom-in;
  margin-top: 0.5em;
  margin-bottom: 0.5em;
}

.resize-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  opacity: 0;
  transition: opacity 0.2s ease;
  z-index: 5;
  touch-action: none;
}

.resize-handle::after {
  content: '';
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 24px;
  border-radius: 1px;
  background: hsl(var(--primary) / 0.5);
}

.message-bubble:hover .resize-handle,
.resize-handle:active {
  opacity: 1;
}

.resize-handle-left {
  left: -3px;
}

.resize-handle-left::after {
  left: 2px;
}

.resize-handle-right {
  right: -3px;
}

.resize-handle-right::after {
  right: 2px;
}
</style>
