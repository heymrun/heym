<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import {
  Loader2,
  CheckCircle2,
  Copy,
  Paperclip,
  XCircle,
  ExternalLink,
  PauseCircle,
  Trash2,
} from "lucide-vue-next";

import type { BoardCard } from "@/types/board";
import { useToast } from "@/composables/useToast";
import { useBoardStore } from "@/stores/board";

const boardStore = useBoardStore();
const { showToast } = useToast();
// No board actions until the Agentic Kanban Model is selected.
const canAct = computed<boolean>(() => boardStore.mapperConfigured && boardStore.canWrite);

const props = defineProps<{ card: BoardCard }>();
const emit = defineEmits<{
  (e: "open", cardId: string): void;
  (e: "clone", cardId: string): void;
  (e: "delete", cardId: string): void;
  (e: "openErrorHistory", cardId: string): void;
}>();
const editingTitle = ref(false);
const editedTitle = ref(props.card.title);
const titleInput = ref<HTMLTextAreaElement | null>(null);
const savingTitle = ref(false);
let titleClickTimer: ReturnType<typeof setTimeout> | null = null;

watch(
  () => props.card.title,
  (title) => {
    if (!editingTitle.value) editedTitle.value = title;
  },
);

async function startTitleEdit(): Promise<void> {
  if (!canAct.value || savingTitle.value) return;
  editedTitle.value = props.card.title;
  editingTitle.value = true;
  await nextTick();
  const input = titleInput.value;
  if (!input) return;
  input.focus();
  input.setSelectionRange(0, input.value.length);
}

function onTitleClick(): void {
  if (titleClickTimer) clearTimeout(titleClickTimer);
  titleClickTimer = setTimeout(() => {
    titleClickTimer = null;
    emit("open", props.card.id);
  }, 250);
}

function onTitleDblClick(): void {
  if (titleClickTimer) {
    clearTimeout(titleClickTimer);
    titleClickTimer = null;
  }
  void startTitleEdit();
}

async function saveTitle(): Promise<void> {
  if (!editingTitle.value || savingTitle.value) return;

  const title = editedTitle.value.trim();
  if (!title) {
    editedTitle.value = props.card.title;
    showToast("Card title cannot be empty", "error");
    await nextTick();
    titleInput.value?.focus();
    return;
  }
  if (title === props.card.title) {
    editingTitle.value = false;
    return;
  }

  savingTitle.value = true;
  try {
    await boardStore.updateCard(props.card.id, { title });
    editedTitle.value = title;
    editingTitle.value = false;
  } catch {
    editedTitle.value = props.card.title;
    showToast("Failed to update card title", "error");
    savingTitle.value = false;
    await nextTick();
    titleInput.value?.focus();
    titleInput.value?.setSelectionRange(0, titleInput.value.value.length);
  } finally {
    savingTitle.value = false;
  }
}

const statusClasses = computed<string>(() => {
  switch (props.card.run_status) {
    case "success":
      return "border-emerald-500/70 bg-emerald-500/10";
    case "failed":
      return "border-red-500/70 bg-red-500/10";
    case "running":
      return "border-amber-500/70 bg-amber-500/10 animate-pulse";
    case "pending":
      return "border-amber-500/70 bg-amber-500/5";
    default:
      return "border-border bg-card";
  }
});

const attachmentCount = computed<number>(() => {
  const raw = props.card.card_metadata?.attachments;
  return Array.isArray(raw) ? raw.length : 0;
});

function onDragStart(event: DragEvent): void {
  event.dataTransfer?.setData("text/board-card", props.card.id);
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
}
</script>

<template>
  <div
    class="group min-w-0 cursor-pointer rounded-lg border p-2.5 text-sm shadow-sm transition-colors hover:border-primary/60 sm:p-3"
    :class="statusClasses"
    :draggable="canAct && !editingTitle"
    :data-testid="`board-card-${card.id}`"
    @dragstart="onDragStart"
    @click="emit('open', card.id)"
  >
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0 flex-1">
        <div
          v-if="editingTitle"
          class="relative"
          @click.stop
          @dblclick.stop
        >
          <textarea
            ref="titleInput"
            v-model="editedTitle"
            rows="3"
            class="w-full resize-none rounded border border-primary/60 bg-background px-1 py-0.5 font-medium leading-5 text-foreground outline-none ring-1 ring-primary/30 disabled:pr-6"
            :disabled="savingTitle"
            :data-testid="`board-card-title-input-${card.id}`"
            :aria-label="`Edit title for ${card.title}`"
            @blur="saveTitle"
            @click.stop
          />
          <Loader2
            v-if="savingTitle"
            class="absolute right-1 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-muted-foreground"
            :data-testid="`board-card-title-saving-${card.id}`"
          />
        </div>
        <span
          v-else
          class="line-clamp-3 whitespace-pre-line break-words font-medium sm:break-normal"
          :data-testid="`board-card-title-${card.id}`"
          @click.stop="onTitleClick"
          @dblclick.stop="onTitleDblClick"
        >{{ card.title }}</span>
      </div>
      <span
        v-if="attachmentCount"
        class="mt-0.5 inline-flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground"
        :title="`${attachmentCount} attachment${attachmentCount > 1 ? 's' : ''}`"
        :data-testid="`board-card-attachments-${card.id}`"
      >
        <Paperclip class="h-3 w-3" />
        {{ attachmentCount }}
      </span>
      <div class="ml-auto shrink-0">
        <div class="group-hover:hidden">
          <Loader2
            v-if="card.run_status === 'running'"
            class="h-4 w-4 animate-spin text-amber-500"
          />
          <PauseCircle
            v-else-if="card.run_status === 'pending'"
            class="h-4 w-4 text-amber-500"
          />
          <CheckCircle2
            v-else-if="card.run_status === 'success'"
            class="h-4 w-4 text-emerald-500"
          />
          <XCircle
            v-else-if="card.run_status === 'failed'"
            class="h-4 w-4 text-red-500"
          />
          <span
            v-else
            class="block h-4 w-4"
          />
        </div>
        <div class="hidden items-center gap-0.5 group-hover:flex">
          <button
            v-if="card.run_status === 'failed'"
            class="flex items-center justify-center gap-0.5 rounded p-0.5 text-red-500 underline decoration-dotted transition-colors hover:bg-red-500/10 hover:text-red-400"
            aria-label="View error history"
            title="View error history"
            :data-testid="`board-card-error-history-${card.id}`"
            @click.stop="emit('openErrorHistory', card.id)"
          >
            <XCircle class="h-3.5 w-3.5" />
            <ExternalLink class="h-3 w-3" />
          </button>
          <button
            class="flex items-center justify-center rounded p-0.5 text-muted-foreground hover:text-primary"
            aria-label="Clone card"
            :data-testid="`board-card-clone-${card.id}`"
            @click.stop="emit('clone', card.id)"
          >
            <Copy class="h-3.5 w-3.5" />
          </button>
          <button
            class="flex items-center justify-center rounded p-0.5 text-muted-foreground hover:text-red-500"
            aria-label="Delete card"
            :data-testid="`board-card-delete-${card.id}`"
            @click.stop="emit('delete', card.id)"
          >
            <Trash2 class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
    <p
      v-if="card.content"
      class="mt-1 line-clamp-2 break-words text-xs text-muted-foreground sm:break-normal"
    >
      {{ card.content }}
    </p>
  </div>
</template>
