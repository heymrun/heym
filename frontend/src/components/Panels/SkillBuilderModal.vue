<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { Download, FileCode2, FileText, Loader2, Send, Sparkles, X } from "lucide-vue-next";

import type { SkillBuilderExistingSkill, SkillBuilderFile } from "@/services/skillBuilderApi";
import type { AgentSkill, AgentSkillFile } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import {
  createSkillFilesZipBlob,
  extractNameFromFrontmatter,
  getSkillZipFileName,
} from "@/lib/skillZipParser";
import { useSkillBuilder } from "@/composables/useSkillBuilder";

interface Props {
  open: boolean;
  credentialId: string;
  model: string;
  existingSkill?: AgentSkill | null;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "save", file: File): void;
  (e: "update:open", value: boolean): void;
}>();

const {
  currentFiles,
  error,
  hasFilesUpdate,
  initialize,
  isStreaming,
  messages,
  reset,
  sendMessage,
} = useSkillBuilder();

const activeFileIndex = ref(0);
const inputText = ref("");
const isDownloading = ref(false);
const isSaving = ref(false);
const localError = ref<string | null>(null);
const modalContainer = ref<HTMLDivElement | null>(null);
const messagesContainer = ref<HTMLDivElement | null>(null);
const keydownCaptureOptions = { capture: true } as const;
const SKILL_BUILDER_MAX_FILE_BYTES = 75 * 1024;
const SKILL_BUILDER_TEXT_EXTENSIONS = new Set([
  "md",
  "py",
]);

function getFileExtension(path: string): string {
  const normalizedPath = path.toLowerCase();
  const lastDot = normalizedPath.lastIndexOf(".");
  return lastDot >= 0 ? normalizedPath.slice(lastDot + 1) : "";
}

function getFileSizeBytes(content: string): number {
  return new TextEncoder().encode(content).length;
}

function canSendFileToSkillBuilder(file: AgentSkillFile): boolean {
  if ((file.encoding ?? "text") !== "text") {
    return false;
  }

  if (!SKILL_BUILDER_TEXT_EXTENSIONS.has(getFileExtension(file.path))) {
    return false;
  }

  return getFileSizeBytes(file.content) <= SKILL_BUILDER_MAX_FILE_BYTES;
}

const existingSkillFiles = computed<AgentSkillFile[]>(() => {
  if (!props.existingSkill) {
    return [];
  }

  return [
    {
      path: "SKILL.md",
      content: props.existingSkill.content,
      encoding: "text",
      mimeType: "text/markdown",
    },
    ...(props.existingSkill.files ?? []),
  ];
});

const existingSkillForApi = computed<SkillBuilderExistingSkill | undefined>(() => {
  if (!props.existingSkill) {
    return undefined;
  }

  const editableFiles = existingSkillFiles.value
    .filter((file) => canSendFileToSkillBuilder(file))
    .map((file) => ({
      path: file.path,
      content: file.content,
    }));

  return {
    name: props.existingSkill.name,
    files: editableFiles,
  };
});

const preservedSkillFiles = computed<AgentSkillFile[]>(() =>
  existingSkillFiles.value.filter((file) => !canSendFileToSkillBuilder(file)),
);

const previewFiles = computed<SkillBuilderFile[]>(() => {
  const mergedFiles = new Map<string, SkillBuilderFile>();

  preservedSkillFiles.value.forEach((file) => {
    if ((file.encoding ?? "text") !== "text") {
      return;
    }
    mergedFiles.set(file.path, { path: file.path, content: file.content });
  });

  currentFiles.value.forEach((file) => {
    mergedFiles.set(file.path, file);
  });

  return Array.from(mergedFiles.values());
});

const preservedFileNote = computed(() => {
  const preservedCount = preservedSkillFiles.value.length;
  if (preservedCount === 0) {
    return null;
  }
  return `${preservedCount} non-editable, large, or non-text file(s) will stay attached to the skill but will not be sent to AI. Skill Builder only edits English Markdown and Python files.`;
});

const modalTitle = computed(() => {
  const skillFile = previewFiles.value.find((file) => file.path.toLowerCase().endsWith("skill.md"));
  const generatedName = skillFile ? extractNameFromFrontmatter(skillFile.content) : "";
  return generatedName || props.existingSkill?.name || "New Skill";
});

const activeFile = computed<SkillBuilderFile | null>(
  () => previewFiles.value[activeFileIndex.value] ?? null,
);

const canPrompt = computed(
  () =>
    !isStreaming.value &&
    !isDownloading.value &&
    !isSaving.value &&
    inputText.value.trim().length > 0 &&
    props.credentialId.trim().length > 0 &&
    props.model.trim().length > 0,
);

const canSave = computed(
  () =>
    hasFilesUpdate.value &&
    previewFiles.value.length > 0 &&
    !isStreaming.value &&
    !isDownloading.value &&
    !isSaving.value,
);

const canDownload = computed(
  () =>
    getSkillArchiveFiles().length > 0 &&
    !isStreaming.value &&
    !isDownloading.value &&
    !isSaving.value,
);

const displayError = computed(() => localError.value ?? error.value);

function getGreeting(): string {
  if (props.existingSkill) {
    return `I loaded "${props.existingSkill.name}" and its editable English Markdown/Python files. Describe the changes you want, and I will update the files on the right.`;
  }
  return "Describe the skill you want to build. I can draft English SKILL.md and Python files, then keep the file preview updated as I work.";
}

function close(): void {
  emit("update:open", false);
}

function focusPromptInput(): void {
  nextTick(() => {
    window.requestAnimationFrame(() => {
      if (!props.open) {
        return;
      }

      const textarea = modalContainer.value?.querySelector("textarea");
      if (!(textarea instanceof HTMLTextAreaElement) || textarea.disabled) {
        return;
      }

      textarea.focus({ preventScroll: true });
      const caretPosition = textarea.value.length;
      textarea.setSelectionRange(caretPosition, caretPosition);
    });
  });
}

function handleWindowKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && props.open) {
    event.preventDefault();
    event.stopImmediatePropagation();
    close();
  }
}

function getZipFileName(): string {
  return getSkillZipFileName(modalTitle.value, "skill-builder");
}

function getSkillArchiveFiles(): AgentSkillFile[] {
  const filesByPath = new Map<string, AgentSkillFile>();

  currentFiles.value.forEach((file) => {
    filesByPath.set(file.path, {
      path: file.path,
      content: file.content,
      encoding: "text",
    });
  });

  preservedSkillFiles.value.forEach((file) => {
    if (filesByPath.has(file.path)) {
      return;
    }

    filesByPath.set(file.path, file);
  });

  return Array.from(filesByPath.values());
}

function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function downloadSkillZip(): Promise<void> {
  if (!canDownload.value) {
    return;
  }

  isDownloading.value = true;
  localError.value = null;

  try {
    const blob = await createSkillFilesZipBlob(getSkillArchiveFiles());
    triggerBlobDownload(blob, getZipFileName());
  } catch (downloadError: unknown) {
    localError.value =
      downloadError instanceof Error ? downloadError.message : "Failed to download skill zip";
  } finally {
    isDownloading.value = false;
  }
}

async function saveSkill(): Promise<void> {
  if (!canSave.value) {
    return;
  }

  isSaving.value = true;
  localError.value = null;

  try {
    const blob = await createSkillFilesZipBlob(getSkillArchiveFiles());
    emit("save", new File([blob], getZipFileName(), { type: "application/zip" }));
  } catch (saveError: unknown) {
    localError.value = saveError instanceof Error ? saveError.message : "Failed to package skill files";
  } finally {
    isSaving.value = false;
  }
}

function submit(): void {
  if (!canPrompt.value) {
    return;
  }

  localError.value = null;
  const prompt = inputText.value.trim();
  inputText.value = "";
  sendMessage(prompt, props.credentialId, props.model, existingSkillForApi.value);
}

function handleInputKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
    return;
  }

  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submit();
  }
}

function getFileIcon(path: string) {
  return path.toLowerCase().endsWith(".md") ? FileText : FileCode2;
}

function renderMarkdown(content: string): string {
  if (!content) return "";
  const html = marked(content, { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      "p", "br", "strong", "em", "u", "s", "code", "pre", "blockquote",
      "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "hr",
      "table", "thead", "tbody", "tr", "th", "td",
    ],
    ALLOWED_ATTR: ["href", "target", "rel"],
  });
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      window.addEventListener("keydown", handleWindowKeydown, keydownCaptureOptions);
      reset();
      inputText.value = "";
      localError.value = null;
      activeFileIndex.value = 0;
      initialize(getGreeting(), existingSkillForApi.value?.files ?? []);
      focusPromptInput();
      nextTick(() => {
        messagesContainer.value?.scrollTo({ top: messagesContainer.value.scrollHeight });
      });
      return;
    }

    window.removeEventListener("keydown", handleWindowKeydown, keydownCaptureOptions);
    reset();
    inputText.value = "";
    localError.value = null;
    activeFileIndex.value = 0;
  },
  { immediate: true },
);

watch(
  messages,
  () => {
    nextTick(() => {
      messagesContainer.value?.scrollTo({ top: messagesContainer.value.scrollHeight });
    });
  },
  { deep: true },
);

watch(
  previewFiles,
  (files) => {
    if (files.length === 0) {
      activeFileIndex.value = 0;
      return;
    }
    if (activeFileIndex.value >= files.length) {
      activeFileIndex.value = files.length - 1;
    }
  },
  { deep: true },
);

onUnmounted(() => {
  window.removeEventListener("keydown", handleWindowKeydown, keydownCaptureOptions);
  reset();
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="close"
    >
      <div
        ref="modalContainer"
        class="flex w-full max-w-[900px] flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-2xl"
        style="height: min(85vh, 700px); width: min(90vw, 900px);"
      >
        <div class="flex items-center gap-3 border-b border-border/60 bg-muted/30 px-5 py-4">
          <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Sparkles class="h-5 w-5" />
          </div>
          <div class="min-w-0 flex-1">
            <p class="text-sm font-semibold">
              Skill Builder
            </p>
            <p class="truncate text-xs text-muted-foreground">
              {{ modalTitle }}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            @click="close"
          >
            <span class="sr-only">Close</span>
            <X class="h-4 w-4" />
          </Button>
        </div>

        <div class="flex min-h-0 flex-1 flex-col md:flex-row">
          <div class="flex min-h-0 min-w-0 flex-1 flex-col border-b border-border/60 md:border-b-0 md:border-r">
            <div
              ref="messagesContainer"
              class="flex-1 space-y-3 overflow-y-auto px-4 py-4"
            >
              <div
                v-for="(message, index) in messages"
                :key="`${message.role}-${index}`"
                :class="[
                  'max-w-[90%] rounded-2xl px-4 py-3 text-sm',
                  message.role === 'user'
                    ? 'ml-auto bg-primary text-primary-foreground'
                    : 'overflow-hidden bg-muted text-foreground',
                ]"
              >
                <template v-if="message.role === 'assistant'">
                  <!-- eslint-disable vue/no-v-html -->
                  <div
                    v-if="message.content"
                    class="markdown-content prose prose-sm max-w-none break-words dark:prose-invert"
                    v-html="renderMarkdown(message.content)"
                  />
                  <!-- eslint-enable vue/no-v-html -->
                </template>
                <template v-else>
                  <div class="whitespace-pre-wrap break-words">
                    {{ message.content }}
                  </div>
                </template>
                <span
                  v-if="message.role === 'assistant' && isStreaming && index === messages.length - 1 && !message.content"
                  class="inline-flex items-center gap-2 text-muted-foreground"
                >
                  <Loader2 class="h-3.5 w-3.5 animate-spin" />
                  Thinking...
                </span>
              </div>
            </div>

            <p
              v-if="displayError"
              class="px-4 pb-2 text-xs text-destructive"
            >
              {{ displayError }}
            </p>

            <div class="border-t border-border/60 px-4 pt-4 pb-2">
              <Textarea
                v-model="inputText"
                :disabled="isStreaming || isDownloading || isSaving || !credentialId || !model"
                :rows="3"
                class="font-normal"
                placeholder="Describe the skill or the changes you want..."
                @keydown="handleInputKeydown"
              />
              <div class="mt-2 flex min-h-11 items-center justify-between gap-3">
                <p class="text-xs leading-none text-muted-foreground">
                  {{ preservedFileNote ?? (credentialId && model ? "Press Enter to send, Shift+Enter for a new line." : "Select an agent credential and model to use AI Build.") }}
                </p>
                <Button
                  class="gap-2"
                  :disabled="!canPrompt"
                  @click="submit"
                >
                  <Send class="h-4 w-4" />
                  Send
                </Button>
              </div>
            </div>
          </div>

          <aside class="flex min-h-0 w-full shrink-0 flex-col md:w-[280px]">
            <div class="border-b border-border/60 px-4 py-3">
              <p class="text-sm font-medium">
                Files
              </p>
              <p class="text-xs text-muted-foreground">
                Read-only preview of generated skill files
              </p>
            </div>

            <div class="flex flex-wrap gap-2 border-b border-border/60 px-3 py-3">
              <button
                v-for="(file, index) in previewFiles"
                :key="file.path"
                type="button"
                :class="[
                  'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors',
                  index === activeFileIndex
                    ? 'border-primary/40 bg-primary/10 text-primary'
                    : 'border-border/60 bg-background text-muted-foreground hover:border-primary/30 hover:text-foreground',
                ]"
                @click="activeFileIndex = index"
              >
                <component
                  :is="getFileIcon(file.path)"
                  class="h-3.5 w-3.5"
                />
                {{ file.path }}
              </button>
            </div>

            <div class="min-h-0 flex-1 overflow-y-auto bg-muted/10 px-4 py-4">
              <pre
                v-if="activeFile"
                class="whitespace-pre-wrap break-words text-xs leading-5 text-foreground"
              >{{ activeFile.content }}</pre>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Generated files will appear here after the assistant calls `set_skill_files`.
              </p>
            </div>

            <div class="border-t border-border/60 p-4">
              <div class="grid gap-2">
                <Button
                  variant="outline"
                  class="gap-2"
                  :disabled="!canDownload"
                  :loading="isDownloading"
                  @click="downloadSkillZip"
                >
                  <Download class="h-4 w-4" />
                  Download ZIP
                </Button>
                <Button
                  class="gap-2"
                  :disabled="!canSave"
                  :loading="isSaving"
                  @click="saveSkill"
                >
                  <Sparkles class="h-4 w-4" />
                  Save &amp; Add
                </Button>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4),
.markdown-content :deep(h5),
.markdown-content :deep(h6) {
  margin-top: 0.75em;
  margin-bottom: 0.4em;
  font-weight: 600;
}

.markdown-content :deep(p) {
  margin-top: 0.4em;
  margin-bottom: 0.4em;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin-top: 0.4em;
  padding-left: 1.25em;
}

.markdown-content :deep(code) {
  border-radius: 0.25rem;
  background: hsl(var(--background) / 0.8);
  padding: 0.125em 0.375em;
  font-size: 0.875em;
}

.markdown-content :deep(pre) {
  overflow-x: auto;
  border-radius: 0.5rem;
  background: hsl(var(--background) / 0.8);
  padding: 0.75em;
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
</style>
