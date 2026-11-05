<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { GripVertical, Plus, Settings2, Trash2, Workflow } from "lucide-vue-next";

import type { BoardCard, BoardColumn } from "@/types/board";
import {
  BOARD_CARD_TOUCH_DRAG_EVENT,
  type BoardCardTouchDragDetail,
} from "@/composables/useBoardCardTouchDrag";
import { useToast } from "@/composables/useToast";
import { useBoardStore } from "@/stores/board";
import BoardCardItem from "./BoardCardItem.vue";

const COLUMN_DRAG_TYPE = "text/board-column";

const props = defineProps<{ column: BoardColumn; index: number }>();
const emit = defineEmits<{
  (e: "openCard", cardId: string): void;
  (e: "openSettings", columnId: string): void;
  (e: "openErrorHistory", cardId: string): void;
}>();

const boardStore = useBoardStore();
const { showToast } = useToast();
const dragOver = ref(false);
const touchDragOver = ref(false);
const columnDragOver = ref(false);
const newCardTitle = ref("");
const lane = ref<HTMLElement | null>(null);
const laneBody = ref<HTMLElement | null>(null);

const cards = computed<BoardCard[]>(() => boardStore.cardsByColumn[props.column.id] ?? []);
// The Agentic Kanban Model is mandatory for anything that runs a workflow (cards, moves).
const canAct = computed<boolean>(() => boardStore.mapperConfigured && boardStore.canWrite);
// Reordering columns runs nothing, so it only needs write access to the board.
const canReorder = computed<boolean>(() => boardStore.canWrite);

function dropIndexFromClientY(clientY: number): number {
  const container = laneBody.value;
  if (!container) return cards.value.length;
  const cardEls = Array.from(container.querySelectorAll<HTMLElement>("[data-board-card]"));
  for (let i = 0; i < cardEls.length; i += 1) {
    const rect = cardEls[i].getBoundingClientRect();
    if (clientY < rect.top + rect.height / 2) return i;
  }
  return cardEls.length;
}

// A running card can still be reordered within its own column (the chain does not
// care about position), but moving it to a different column while it runs would
// race the active chain against whatever the new column starts. Backend rejects a
// concurrent enqueue either way; this just avoids the round trip and explains why.
function blocksCrossColumnMove(cardId: string, targetColumnId: string): boolean {
  const card = boardStore.activeBoard?.cards.find((c) => c.id === cardId);
  if (!card || card.column_id === targetColumnId) return false;
  if (card.run_status !== "running") return false;
  showToast("This card is still running; wait for it to finish before moving it.", "error");
  return true;
}

// Moving a card that waits for a review cancels that review (it is never approved), so the
// person moving it confirms first.
function confirmsPendingMove(cardId: string, targetColumnId: string): boolean {
  const card = boardStore.activeBoard?.cards.find((c) => c.id === cardId);
  if (!card || card.column_id === targetColumnId || card.run_status !== "pending") return true;
  return window.confirm(
    "This card is waiting for a review. Moving it cancels that review; it does not approve it. Move it anyway?",
  );
}

function containsPoint(clientX: number, clientY: number): boolean {
  const rect = lane.value?.getBoundingClientRect();
  if (!rect) return false;
  return (
    clientX >= rect.left &&
    clientX <= rect.right &&
    clientY >= rect.top &&
    clientY <= rect.bottom
  );
}

function onCardTouchDrag(event: Event): void {
  const detail = (event as CustomEvent<BoardCardTouchDragDetail>).detail;
  if (detail.phase === "cancel") {
    touchDragOver.value = false;
    return;
  }

  const isOverLane = canAct.value && containsPoint(detail.clientX, detail.clientY);
  touchDragOver.value = detail.phase !== "end" && isOverLane;
  if (detail.phase === "end" && isOverLane) {
    if (blocksCrossColumnMove(detail.cardId, props.column.id)) return;
    if (!confirmsPendingMove(detail.cardId, props.column.id)) return;
    void boardStore.moveCard(
      detail.cardId,
      props.column.id,
      dropIndexFromClientY(detail.clientY),
    );
  }
}

onMounted(() => {
  window.addEventListener(BOARD_CARD_TOUCH_DRAG_EVENT, onCardTouchDrag);
});

onUnmounted(() => {
  window.removeEventListener(BOARD_CARD_TOUCH_DRAG_EVENT, onCardTouchDrag);
});

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
  if (blocksCrossColumnMove(cardId, props.column.id)) return;
  if (!confirmsPendingMove(cardId, props.column.id)) return;
  void boardStore.moveCard(cardId, props.column.id, dropIndexFromClientY(event.clientY));
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

async function emptyColumn(): Promise<void> {
  if (!window.confirm(`Delete all cards in "${props.column.name}" column?`)) return;
  await boardStore.emptyColumn(props.column.id);
}
</script>

<template>
  <div
    ref="lane"
    class="flex h-full min-h-0 w-[calc(100vw-2.5rem)] max-w-[18rem] shrink-0 flex-col overflow-hidden rounded-xl border border-border/60 bg-muted/30 md:w-72"
    :class="[
      dragOver ? 'ring-2 ring-primary/50' : '',
      touchDragOver ? 'bg-primary/5 ring-2 ring-primary/80' : '',
      columnDragOver ? 'ring-2 ring-primary' : '',
    ]"
    :data-touch-drag-over="touchDragOver ? 'true' : undefined"
    :data-testid="`board-column-${column.name}`"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <!-- The header is the column's drag handle; the body still takes card drops. -->
    <div
      class="group/header flex shrink-0 items-center gap-2 px-3 py-2.5"
      :class="canReorder ? 'cursor-grab active:cursor-grabbing' : ''"
      :draggable="canReorder"
      :data-testid="`board-column-handle-${column.name}`"
      @dragstart="onColumnDragStart"
    >
      <GripVertical
        class="-ml-1.5 hidden h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/header:opacity-100 md:block"
      />
      <span
        class="h-2.5 w-2.5 rounded-full"
        :style="{ backgroundColor: column.color ?? 'var(--muted-foreground)' }"
      />
      <div class="flex min-w-0 items-center gap-2">
        <span class="truncate text-sm font-semibold">{{ column.name }}</span>
        <span class="shrink-0 text-xs text-muted-foreground">{{ cards.length }}</span>
      </div>
      <div class="ml-auto flex shrink-0 items-center gap-1">
        <span
          v-if="column.workflows.length"
          class="inline-flex items-center gap-1 rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary dark:text-violet-300"
          :title="column.workflows.map((w) => w.workflow_name).join(' → ')"
        >
          <Workflow class="h-3 w-3" />
          {{ column.workflows.length }}
        </span>
        <button
          v-if="boardStore.canWrite && cards.length > 0"
          class="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          :aria-label="`Empty ${column.name}`"
          @click="emptyColumn"
        >
          <Trash2 class="h-4 w-4" />
        </button>
        <button
          v-if="boardStore.canWrite"
          class="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          :aria-label="`Configure ${column.name}`"
          :data-testid="`board-column-settings-${column.id}`"
          @click="emit('openSettings', column.id)"
        >
          <Settings2 class="h-4 w-4" />
        </button>
      </div>
    </div>
    <div
      ref="laneBody"
      class="flex min-h-24 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2"
      :data-testid="`board-column-cards-${column.id}`"
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
          @open-error-history="emit('openErrorHistory', $event)"
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
        class="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
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
