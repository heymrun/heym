<script setup lang="ts">
import { computed, ref } from "vue";
import { ChevronDown, ChevronRight, Clock, Download, Loader2, Sparkles, Trash2, Upload } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import {
  getSkillFileImageSrc,
  getSkillFilesSortedForDisplay,
  isImageSkillFile,
  isTextSkillFile,
} from "@/lib/skillFilePreview";
import type { AgentSkill } from "@/types/workflow";

interface Props {
  skill: AgentSkill;
  index: number;
  expanded: boolean;
  aiEditDisabled?: boolean;
  downloadLoading?: boolean;
}

const props = defineProps<Props>();
const sortedSkillFiles = computed(() => getSkillFilesSortedForDisplay(props.skill.files ?? []));

const emit = defineEmits<{
  (e: "toggle-expand"): void;
  (e: "ai-edit"): void;
  (e: "download"): void;
  (e: "remove"): void;
  (e: "history"): void;
  (e: "update:name", value: string): void;
  (e: "update:timeout-seconds", value: number): void;
  (e: "update:drive-files-enabled", value: boolean): void;
  (e: "update:content", value: string): void;
  (e: "update:file-content", fileIndex: number, value: string): void;
  (e: "add-files", files: File[]): void;
  (e: "remove-file", fileIndex: number): void;
}>();

const fileInputRef = ref<HTMLInputElement | null>(null);
const isFileDragActive = ref(false);

function openFilePicker(): void {
  fileInputRef.value?.click();
}

function emitFiles(fileList: FileList | null | undefined): void {
  const files = Array.from(fileList ?? []);
  if (files.length === 0) {
    return;
  }
  emit("add-files", files);
}

function handleFileInputChange(event: Event): void {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) {
    return;
  }

  emitFiles(input.files);
  input.value = "";
}

function handleFileDragOver(event: DragEvent): void {
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = "copy";
  }
  isFileDragActive.value = true;
}

function handleFileDragLeave(event: DragEvent): void {
  const currentTarget = event.currentTarget;
  const relatedTarget = event.relatedTarget;
  if (
    currentTarget instanceof HTMLElement &&
    relatedTarget instanceof Node &&
    currentTarget.contains(relatedTarget)
  ) {
    return;
  }
  isFileDragActive.value = false;
}

function handleFileDrop(event: DragEvent): void {
  isFileDragActive.value = false;
  emitFiles(event.dataTransfer?.files);
}
</script>

<template>
  <div class="rounded border p-3 space-y-2">
    <button
      type="button"
      class="flex w-full items-center gap-1.5 text-left text-sm font-medium hover:text-primary"
      :title="`Skill ${index + 1}: ${skill.name || '(unnamed)'}`"
      @click="emit('toggle-expand')"
    >
      <ChevronRight
        v-if="!expanded"
        class="w-3.5 h-3.5 shrink-0"
      />
      <ChevronDown
        v-else
        class="w-3.5 h-3.5 shrink-0"
      />
      <span class="break-words leading-tight">
        Skill {{ index + 1 }}: {{ skill.name || "(unnamed)" }}
      </span>
    </button>

    <div class="grid w-full grid-cols-4 gap-1.5 rounded-lg border border-border/60 bg-muted/10 p-1.5">
      <button
        type="button"
        class="flex h-7 w-full items-center justify-center rounded-md text-primary transition-colors hover:bg-primary/10 hover:text-primary disabled:pointer-events-none disabled:opacity-50"
        :disabled="aiEditDisabled"
        title="Edit with AI"
        aria-label="Edit with AI"
        @click="emit('ai-edit')"
      >
        <Sparkles class="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        class="flex h-7 w-full items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
        :disabled="downloadLoading"
        title="Download skill ZIP"
        aria-label="Download skill ZIP"
        @click="emit('download')"
      >
        <Loader2
          v-if="downloadLoading"
          class="w-3.5 h-3.5 animate-spin"
        />
        <Download
          v-else
          class="w-3.5 h-3.5"
        />
      </button>
      <button
        type="button"
        class="flex h-7 w-full items-center justify-center rounded-md text-destructive transition-colors hover:bg-destructive/10 hover:text-destructive"
        title="Remove skill"
        aria-label="Remove skill"
        @click="emit('remove')"
      >
        <Trash2 class="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        class="flex h-7 w-full items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        title="Skill history"
        aria-label="Skill history"
        @click="emit('history')"
      >
        <Clock class="w-3.5 h-3.5" />
      </button>
    </div>

    <div
      v-if="expanded"
      class="space-y-2 pt-2 border-t"
    >
      <div>
        <Label class="text-xs">Name</Label>
        <Input
          :model-value="skill.name"
          placeholder="skill-name"
          @update:model-value="emit('update:name', $event)"
        />
      </div>
      <div>
        <Label class="text-xs">Timeout (seconds)</Label>
        <Input
          type="number"
          :model-value="String(skill.timeoutSeconds ?? 30)"
          min="1"
          max="3600"
          placeholder="30"
          @update:model-value="emit('update:timeout-seconds', parseInt($event, 10) || 30)"
        />
      </div>
      <div class="rounded border border-border/60 bg-muted/20 p-3">
        <label class="flex items-start gap-2">
          <input
            type="checkbox"
            class="mt-0.5 h-4 w-4 rounded border-input bg-background"
            :checked="!!skill.driveFilesEnabled"
            @change="emit('update:drive-files-enabled', ($event.target as HTMLInputElement).checked)"
          >
          <span class="min-w-0">
            <span class="block text-sm font-medium text-foreground">Enable Drive files</span>
            <span class="block text-xs leading-snug text-muted-foreground">Allow this skill to read accessible Drive files by id or filename during execution.</span>
          </span>
        </label>
      </div>
      <div>
        <Label class="text-xs">SKILL.md Content</Label>
        <Textarea
          :model-value="skill.content"
          placeholder="---&#10;name: my-skill&#10;---&#10;&#10;Instructions..."
          :rows="6"
          class="font-mono text-xs"
          @update:model-value="emit('update:content', $event)"
        />
      </div>
      <div class="py-2">
        <div
          :class="[
            'rounded border border-dashed p-3 text-xs transition-colors',
            isFileDragActive ? 'border-primary bg-primary/5' : 'border-border bg-muted/10',
          ]"
          @dragenter.stop.prevent="isFileDragActive = true"
          @dragover.stop.prevent="handleFileDragOver"
          @dragleave.stop.prevent="handleFileDragLeave"
          @drop.stop.prevent="handleFileDrop"
        >
          <input
            ref="fileInputRef"
            type="file"
            class="sr-only"
            multiple
            @change="handleFileInputChange"
          >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="text-muted-foreground">
              Drop files here to attach them to this skill.
            </p>
            <Button
              variant="outline"
              size="sm"
              class="gap-1"
              @click="openFilePicker"
            >
              <Upload class="w-3.5 h-3.5" />
              Add files
            </Button>
          </div>
        </div>
      </div>
      <div
        v-if="skill.files?.length"
        class="space-y-1"
      >
        <Label class="text-xs">Files ({{ skill.files.length }})</Label>
        <div
          v-for="{ file, originalIndex } in sortedSkillFiles"
          :key="file.path"
          class="rounded border bg-muted/20 p-2 min-w-0"
        >
          <div class="flex justify-between items-center gap-2 mb-1 min-w-0">
            <span
              class="text-xs font-mono min-w-0 flex-1 truncate"
              :title="file.path"
            >{{ file.path }}</span>
            <Button
              variant="ghost"
              size="sm"
              class="gap-1 shrink-0 text-destructive hover:text-destructive hover:bg-destructive/10"
              @click="emit('remove-file', originalIndex)"
            >
              <Trash2 class="w-3.5 h-3.5" />
              Remove
            </Button>
          </div>
          <div
            v-if="isImageSkillFile(file)"
            class="space-y-2"
          >
            <img
              v-if="getSkillFileImageSrc(file)"
              :src="getSkillFileImageSrc(file)"
              :alt="file.path"
              class="max-h-56 w-auto max-w-full rounded border bg-background object-contain"
            >
            <p class="text-xs text-muted-foreground">
              Image preview stored as base64 to keep workflow saves UTF-8 safe.
            </p>
          </div>
          <Textarea
            v-else-if="isTextSkillFile(file)"
            :model-value="file.content"
            :rows="4"
            class="font-mono text-xs"
            @update:model-value="emit('update:file-content', originalIndex, $event)"
          />
          <p
            v-else
            class="text-xs text-muted-foreground"
          >
            Binary file stored as base64. Editing is disabled in the workflow editor.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
