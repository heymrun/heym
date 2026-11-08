<script setup lang="ts">
import { Loader2, Paperclip, X } from "lucide-vue-next";

import type { AttachedFile } from "@/composables/useFileAttachment";

interface Props {
  files: readonly AttachedFile[];
  errors: readonly string[];
}

defineProps<Props>();

const emit = defineEmits<{
  remove: [key: string];
  "dismiss-errors": [];
}>();

function sizeLabel(file: AttachedFile): string {
  return file.sizeKb > 0 ? `${file.sizeKb} KB` : "<1 KB";
}
</script>

<template>
  <div
    v-if="files.length > 0 || errors.length > 0"
    class="flex w-full flex-col gap-1.5"
  >
    <div
      v-if="files.length > 0"
      class="flex flex-wrap items-center gap-1.5"
      data-testid="chat-attachment-chips"
    >
      <div
        v-for="file in files"
        :key="file.key"
        class="flex max-w-xs items-center gap-1.5 rounded-lg border border-border/40 bg-muted/60 px-2.5 py-1 text-xs text-foreground"
        :title="file.name"
      >
        <Loader2
          v-if="file.pending"
          class="h-3 w-3 shrink-0 animate-spin text-muted-foreground"
        />
        <Paperclip
          v-else
          class="h-3 w-3 shrink-0 text-muted-foreground"
        />
        <span class="truncate">{{ file.name }}</span>
        <span
          v-if="!file.pending"
          class="shrink-0 text-muted-foreground"
        >· {{ sizeLabel(file) }}</span>
        <button
          type="button"
          class="ml-0.5 shrink-0 rounded p-0.5 hover:bg-muted/80"
          :aria-label="`Remove ${file.name}`"
          @click="emit('remove', file.key)"
        >
          <X class="h-3 w-3" />
        </button>
      </div>
    </div>
    <div
      v-if="errors.length > 0"
      class="flex items-start gap-1.5 text-xs text-destructive"
      role="alert"
    >
      <ul class="min-w-0 flex-1 space-y-0.5">
        <li
          v-for="(error, index) in errors"
          :key="index"
          class="break-words"
        >
          {{ error }}
        </li>
      </ul>
      <button
        type="button"
        class="shrink-0 rounded p-0.5 hover:bg-destructive/10"
        aria-label="Dismiss"
        @click="emit('dismiss-errors')"
      >
        <X class="h-3 w-3" />
      </button>
    </div>
  </div>
</template>
