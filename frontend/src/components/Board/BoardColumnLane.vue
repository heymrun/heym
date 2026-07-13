<script setup lang="ts">
import { computed, ref } from "vue";
import { GripVertical, Plus, Settings2, Workflow } from "lucide-vue-next";

import type { BoardCard, BoardColumn } from "@/types/board";
import { useBoardStore } from "@/stores/board";
import BoardCardItem from "./BoardCardItem.vue";

const COLUMN_DRAG_TYPE = "text/board-column";

const props = defineProps<{ column: BoardColumn; index: number }>();
const emit = defineEmits<{
  (e: "openCard", cardId: string): void;
  (e: "openSettings", columnId: string): void;
}>();

const boardStore = useBoardStore();
const dragOver = ref(false);
const columnDragOver = ref(false);
const newCardTitle = ref("");
const laneBody = ref<HTMLElement | null>(null);

const cards = computed<BoardCard[]>(() => boardStore.cardsByColumn[props.column.id] ?? []);
// The Agentic Kanban Model is mandatory for anything that runs a workflow (cards, moves).
const canAct = computed<boolean>(() => boardStore.mapperConfigured && boardStore.canWrite);
// Reordering columns runs nothing, so it only needs write access to the board.
const canReorder = computed<boolean>(() => boardStore.canWrite);

function dropIndexFromPointer(event: DragEvent): number {
  const container = laneBody.value;
  if (!container) return cards.value.length;
  const cardEls = Array.from(container.querySelectorAll<HTMLElement>("[data-board-card]"));
  for (let i = 0; i < cardEls.length; i += 1) {
    const rect = cardEls[i].getBoundingClientRect();
    if (event.clientY < rect.top + rect.height / 2) return i;
  }
  return cardEls.length;
}

// A lane accepts two kinds of drag: a card (dropped into this column) and another column
// (dropped at this column's place). Only the data *type* is readable during dragover.
function isColumnDrag(event: DragEvent): boolean {
  return event.dataTransfer?.types.includes(COLUMN_DRAG_TYPE) ?? false;
}

function onColumnDragStart(event: DragEvent): void {
  if (!canReorder.value) return;
  event.dataTransfer?.setData(COLUMN_DRAG_TYPE, props.column.id);
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
}

function onDragOver(event: DragEvent): void {
  if (isColumnDrag(event)) {
    if (!canReorder.value) return;
    event.preventDefault();
    columnDragOver.value = true;
    return;
  }
  if (!canAct.value) return;
  event.preventDefault();
  dragOver.value = true;
}

function onDragLeave(): void {
  dragOver.value = false;
  columnDragOver.value = false;
}

function onDrop(event: DragEvent): void {
  event.preventDefault();
  dragOver.value = false;
  columnDragOver.value = false;
  const columnId = event.dataTransfer?.getData(COLUMN_DRAG_TYPE);
  if (columnId) {
    if (canReorder.value && columnId !== props.column.id) {
      void boardStore.moveColumn(columnId, props.index);
    }
    return;
  }
  if (!canAct.value) return;
  const cardId = event.dataTransfer?.getData("text/board-card");
  if (!cardId) return;
  void boardStore.moveCard(cardId, props.column.id, dropIndexFromPointer(event));
}

async function addCard(): Promise<void> {
  if (!canAct.value) return;
  const title = newCardTitle.value.trim();
  if (!title) return;
  newCardTitle.value = "";
  await boardStore.createCard(title, props.column.id);
}

async function deleteCard(cardId: string): Promise<void> {
  const card = cards.value.find((c) => c.id === cardId);
  if (!window.confirm(`Delete card "${card?.title ?? ""}"?`)) return;
  await boardStore.deleteCard(cardId);
}
</script>

<template>
  <div
    class="flex w-72 shrink-0 flex-col rounded-xl border border-border/60 bg-muted/30"
    :class="[
      dragOver ? 'ring-2 ring-primary/50' : '',
      columnDragOver ? 'ring-2 ring-primary' : '',
    ]"
    :data-testid="`board-column-${column.name}`"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <!-- The header is the column's drag handle; the body still takes card drops. -->
    <div
      class="group/header flex items-center gap-2 px-3 py-2.5"
      :class="canReorder ? 'cursor-grab active:cursor-grabbing' : ''"
      :draggable="canReorder"
      :data-testid="`board-column-handle-${column.name}`"
      @dragstart="onColumnDragStart"
    >
      <GripVertical
        class="-ml-1.5 h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/header:opacity-100"
      />
      <span
        class="h-2.5 w-2.5 rounded-full"
        :style="{ backgroundColor: column.color ?? 'var(--muted-foreground)' }"
      />
      <span class="truncate text-sm font-semibold">{{ column.name }}</span>
      <span class="text-xs text-muted-foreground">{{ cards.length }}</span>
      <span
        v-if="column.workflows.length"
        class="ml-auto inline-flex items-center gap-1 rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary dark:text-violet-300"
        :title="column.workflows.map((w) => w.workflow_name).join(' → ')"
      >
        <Workflow class="h-3 w-3" />
        {{ column.workflows.length }}
      </span>
      <button
        class="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        :class="column.workflows.length ? '' : 'ml-auto'"
        :aria-label="`Configure ${column.name}`"
        @click="emit('openSettings', column.id)"
      >
        <Settings2 class="h-4 w-4" />
      </button>
    </div>
    <div
      ref="laneBody"
      class="flex min-h-24 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2"
    >
      <div
        v-for="(card, cardIndex) in cards"
        :key="card.id"
        class="board-enter"
        :style="{ animationDelay: `${cardIndex * 45}ms` }"
        data-board-card
      >
        <BoardCardItem
          :card="card"
          @open="emit('openCard', $event)"
          @clone="boardStore.cloneCard"
          @delete="deleteCard"
        />
      </div>
    </div>
    <div class="flex items-center gap-1 border-t border-border/40 p-2">
      <Plus class="h-4 w-4 text-muted-foreground" />
      <input
        v-model="newCardTitle"
        type="text"
        :disabled="!canAct"
        :placeholder="canAct ? 'Add a card' : 'Set the Agentic Kanban Model in board settings first'"
        :title="canAct ? '' : 'Pick a credential and model above to use the board'"
        class="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
        @keydown.enter="addCard"
      >
    </div>
  </div>
</template>

<style scoped>
/* Runs once when a lane/card first mounts (board open or switch), not on poll updates. */
.board-enter {
  animation: board-enter 0.32s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes board-enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
