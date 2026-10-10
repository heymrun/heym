<script setup lang="ts">
import { computed, ref } from "vue";
import { FileUp, X } from "lucide-vue-next";

import { acceptAttribute, fileRejection } from "@/lib/fileAccept";

const props = withDefaults(
  defineProps<{
    /** The File Upload trigger's label, shown as the field name. */
    label: string;
    file: File | null;
    allowedTypes?: string[];
    maxSizeMb: number;
    disabled?: boolean;
  }>(),
  { allowedTypes: () => [], disabled: false },
);

const emit = defineEmits<{
  select: [file: File | null];
}>();

const inputRef = ref<HTMLInputElement | null>(null);
const dragging = ref(false);
const rejection = ref<string | null>(null);
const accept = computed(() => acceptAttribute(props.allowedTypes));
const hint = computed(() => {
  const types = props.allowedTypes.length > 0 ? props.allowedTypes.join(", ") : "Any file";
  return `${types}, up to ${props.maxSizeMb} MB`;
});

function choose(file: File | undefined): void {
  if (!file || props.disabled) return;
  rejection.value = fileRejection(file, props.allowedTypes, props.maxSizeMb);
  if (!rejection.value) emit("select", file);
}

function onDrop(event: DragEvent): void {
  dragging.value = false;
  choose(event.dataTransfer?.files?.[0]);
}

function onPick(event: Event): void {
  const input = event.target as HTMLInputElement;
  choose(input.files?.[0]);
  input.value = "";
}

function clear(): void {
  rejection.value = null;
  emit("select", null);
}
</script>

<template>
  <div class="space-y-1.5">
    <div class="block text-sm font-medium text-foreground">
      {{ label }}
    </div>
    <div
      class="flex min-h-[72px] items-center gap-3 rounded-2xl border border-dashed px-4 py-3 text-sm transition-colors"
      :class="[
        dragging ? 'border-primary bg-primary/5' : 'border-border/60',
        disabled ? 'opacity-60' : 'cursor-pointer hover:border-primary/60',
      ]"
      role="button"
      :tabindex="disabled ? -1 : 0"
      :aria-label="`Choose a file for ${label}`"
      data-testid="file-drop-input"
      @click="inputRef?.click()"
      @keydown.enter.prevent="inputRef?.click()"
      @dragover.prevent="dragging = !disabled"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <FileUp class="h-5 w-5 shrink-0 text-muted-foreground" />
      <div
        v-if="file"
        class="min-w-0 flex-1"
      >
        <div class="truncate font-medium text-foreground">
          {{ file.name }}
        </div>
        <div class="text-xs text-muted-foreground">
          {{ (file.size / 1024).toFixed(1) }} KB
        </div>
      </div>
      <div
        v-else
        class="min-w-0 flex-1 text-muted-foreground"
      >
        <div>Drop a file here or click to choose one</div>
        <div class="text-xs">
          {{ hint }}
        </div>
      </div>
      <button
        v-if="file && !disabled"
        type="button"
        class="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        aria-label="Remove file"
        @click.stop="clear"
      >
        <X class="h-4 w-4" />
      </button>
      <input
        ref="inputRef"
        type="file"
        class="hidden"
        :accept="accept"
        :disabled="disabled"
        @change="onPick"
      >
    </div>
    <p
      v-if="rejection"
      class="text-xs text-destructive"
      role="alert"
    >
      {{ rejection }}
    </p>
  </div>
</template>
