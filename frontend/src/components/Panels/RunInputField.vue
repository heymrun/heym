<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { Loader2, Paperclip, Upload } from "lucide-vue-next";

import Textarea from "@/components/ui/Textarea.vue";
import { readFileForInputField } from "@/lib/inputFieldFile";
import { cn } from "@/lib/utils";

interface Props {
  fieldKey: string;
  modelValue?: string;
  placeholder?: string;
  disabled?: boolean;
  panelFileDragActive?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: "",
  placeholder: "",
  disabled: false,
  panelFileDragActive: false,
});

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "file-dropped"): void;
}>();

const isFileDragOver = ref(false);
const attachedFileName = ref<string | null>(null);
const lastFileContent = ref<string | null>(null);
const fileError = ref<string | null>(null);
const isLoading = ref(false);
const fileInputRef = ref<HTMLInputElement | null>(null);

const showDropPreview = computed(
  () => isFileDragOver.value || props.panelFileDragActive,
);

const effectivePlaceholder = computed(() =>
  showDropPreview.value ? "Drop file here…" : props.placeholder,
);

watch(
  () => props.modelValue,
  (value) => {
    if (lastFileContent.value !== null && value !== lastFileContent.value) {
      attachedFileName.value = null;
      lastFileContent.value = null;
    }
  },
);

function isFileDragEvent(event: DragEvent): boolean {
  return event.dataTransfer?.types.includes("Files") ?? false;
}

function setFileDragOver(active: boolean): void {
  isFileDragOver.value = active;
}

function handleDragEnter(event: DragEvent): void {
  if (props.disabled || !isFileDragEvent(event)) return;
  event.preventDefault();
  isFileDragOver.value = true;
}

function handleDragLeave(event: DragEvent): void {
  if (props.disabled) return;
  event.preventDefault();

  const current = event.currentTarget as HTMLElement;
  const related = event.relatedTarget as Node | null;
  if (related && current.contains(related)) return;

  isFileDragOver.value = false;
}

function handleDragOver(event: DragEvent): void {
  if (props.disabled || !isFileDragEvent(event)) return;
  event.preventDefault();
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = "copy";
  }
  isFileDragOver.value = true;
}

function handleDocumentDragEnd(): void {
  setFileDragOver(false);
}

watch(isFileDragOver, (active) => {
  if (active) {
    document.addEventListener("dragend", handleDocumentDragEnd);
    document.addEventListener("drop", handleDocumentDragEnd);
  } else {
    document.removeEventListener("dragend", handleDocumentDragEnd);
    document.removeEventListener("drop", handleDocumentDragEnd);
  }
});

onUnmounted(() => {
  document.removeEventListener("dragend", handleDocumentDragEnd);
  document.removeEventListener("drop", handleDocumentDragEnd);
});

async function processFile(file: File): Promise<void> {
  if (props.disabled) return;

  fileError.value = null;
  isLoading.value = true;
  try {
    const result = await readFileForInputField(file);
    lastFileContent.value = result.content;
    attachedFileName.value = result.name;
    emit("update:modelValue", result.content);
  } catch (error) {
    fileError.value = error instanceof Error ? error.message : "Failed to read file";
  } finally {
    isLoading.value = false;
  }
}

async function handleDrop(event: DragEvent): Promise<void> {
  if (props.disabled) return;
  event.preventDefault();
  setFileDragOver(false);
  emit("file-dropped");

  const file = event.dataTransfer?.files[0];
  if (!file) return;

  await processFile(file);
}

async function handleFileInputChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;

  await processFile(file);
  input.value = "";
}

function openFilePicker(): void {
  if (props.disabled || isLoading.value) return;
  fileInputRef.value?.click();
}
</script>

<template>
  <div class="space-y-1 min-w-0">
    <div
      class="relative min-w-0 rounded-xl transition-all duration-200"
      :class="showDropPreview && 'ring-2 ring-primary/60 shadow-[0_0_0_4px_hsl(var(--primary)/0.08)]'"
      @dragenter="handleDragEnter"
      @dragleave="handleDragLeave"
      @dragover="handleDragOver"
      @drop="handleDrop"
    >
      <Textarea
        :model-value="modelValue"
        :placeholder="effectivePlaceholder"
        :disabled="disabled || isLoading"
        :rows="3"
        :class="cn(
          'min-w-0 w-full pr-10 transition-all duration-200',
          showDropPreview && 'border-primary/50 bg-primary/[0.03]',
        )"
        @update:model-value="emit('update:modelValue', $event)"
      />

      <Transition name="run-input-drop">
        <div
          v-if="showDropPreview"
          class="run-input-drop-overlay absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-primary/[0.06] backdrop-blur-[1px] pointer-events-none"
          aria-hidden="true"
        >
          <div class="run-input-drop-content flex flex-col items-center gap-1.5 px-4 text-center">
            <div class="run-input-drop-icon flex h-9 w-9 items-center justify-center rounded-xl bg-primary/15">
              <Upload class="h-4 w-4 text-primary" />
            </div>
            <p class="text-sm font-medium text-primary">
              Drop file here
            </p>
            <p class="text-xs text-muted-foreground">
              Release to fill {{ fieldKey }}
            </p>
          </div>
        </div>
      </Transition>

      <button
        type="button"
        class="absolute bottom-2 right-2 z-20 flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground opacity-40 transition-opacity hover:opacity-70 disabled:pointer-events-none disabled:opacity-20"
        :disabled="disabled || isLoading"
        :aria-label="`Attach file to ${fieldKey}`"
        @click="openFilePicker"
      >
        <Loader2
          v-if="isLoading"
          class="h-4 w-4 animate-spin"
        />
        <Paperclip
          v-else
          class="h-4 w-4"
        />
      </button>
      <input
        ref="fileInputRef"
        type="file"
        class="hidden"
        :disabled="disabled || isLoading"
        @change="handleFileInputChange"
      >
    </div>
    <p
      v-if="attachedFileName"
      class="text-xs text-muted-foreground truncate"
    >
      {{ attachedFileName }}
    </p>
    <p
      v-if="fileError"
      class="text-xs text-red-500"
    >
      {{ fileError }}
    </p>
  </div>
</template>

<style scoped>
.run-input-drop-enter-active,
.run-input-drop-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.run-input-drop-enter-from,
.run-input-drop-leave-to {
  opacity: 0;
  transform: scale(0.98);
}

.run-input-drop-overlay {
  animation: run-input-border-pulse 1.2s ease-in-out infinite;
}

.run-input-drop-icon {
  animation: run-input-icon-bounce 1.2s ease-in-out infinite;
}

.run-input-drop-content {
  animation: run-input-content-fade 0.2s ease-out;
}

@keyframes run-input-border-pulse {
  0%,
  100% {
    border-color: hsl(var(--primary) / 0.45);
    background-color: hsl(var(--primary) / 0.04);
  }

  50% {
    border-color: hsl(var(--primary) / 0.9);
    background-color: hsl(var(--primary) / 0.1);
  }
}

@keyframes run-input-icon-bounce {
  0%,
  100% {
    transform: translateY(0);
  }

  50% {
    transform: translateY(-3px);
  }
}

@keyframes run-input-content-fade {
  from {
    opacity: 0;
    transform: translateY(4px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
