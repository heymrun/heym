<script setup lang="ts">
import { computed } from "vue";
import {
  Loader2,
  CheckCircle2,
  Copy,
  Paperclip,
  XCircle,
  PauseCircle,
  Trash2,
} from "lucide-vue-next";

import type { BoardCard } from "@/types/board";
import { useBoardStore } from "@/stores/board";

const boardStore = useBoardStore();
// No board actions until the Agentic Kanban Model is selected.
const canAct = computed<boolean>(() => boardStore.mapperConfigured && boardStore.canWrite);

const props = defineProps<{ card: BoardCard }>();
const emit = defineEmits<{
  (e: "open", cardId: string): void;
  (e: "clone", cardId: string): void;
  (e: "delete", cardId: string): void;
}>();

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
    class="group cursor-pointer rounded-lg border p-3 text-sm shadow-sm transition-colors hover:border-primary/60"
    :class="statusClasses"
    :draggable="canAct"
    :data-testid="`board-card-${card.id}`"
    @dragstart="onDragStart"
    @click="emit('open', card.id)"
  >
    <div class="flex items-start justify-between gap-2">
      <span class="line-clamp-2 font-medium">{{ card.title }}</span>
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
      class="mt-1 line-clamp-2 text-xs text-muted-foreground"
    >
      {{ card.content }}
    </p>
  </div>
</template>
