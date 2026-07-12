<script setup lang="ts">
import { computed, ref } from "vue";
import { Plus, Settings2, Workflow } from "lucide-vue-next";

import type { BoardCard, BoardColumn } from "@/types/board";
import { useBoardStore } from "@/stores/board";
import BoardCardItem from "./BoardCardItem.vue";

const props = defineProps<{ column: BoardColumn }>();
const emit = defineEmits<{
  (e: "openCard", cardId: string): void;
  (e: "openSettings", columnId: string): void;
}>();

const boardStore = useBoardStore();
const dragOver = ref(false);
const newCardTitle = ref("");
const laneBody = ref<HTMLElement | null>(null);

const cards = computed<BoardCard[]>(() => boardStore.cardsByColumn[props.column.id] ?? []);

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

function onDragOver(event: DragEvent): void {
  event.preventDefault();
  dragOver.value = true;
}

function onDrop(event: DragEvent): void {
  event.preventDefault();
  dragOver.value = false;
  const cardId = event.dataTransfer?.getData("text/board-card");
  if (!cardId) return;
  void boardStore.moveCard(cardId, props.column.id, dropIndexFromPointer(event));
}

async function addCard(): Promise<void> {
  const title = newCardTitle.value.trim();
  if (!title) return;
  newCardTitle.value = "";
  await boardStore.createCard(title, props.column.id);
}
</script>

<template>
  <div
    class="flex w-72 shrink-0 flex-col rounded-xl border border-border/60 bg-muted/30"
    :class="dragOver ? 'ring-2 ring-primary/50' : ''"
    :data-testid="`board-column-${column.name}`"
    @dragover="onDragOver"
    @dragleave="dragOver = false"
    @drop="onDrop"
  >
    <div class="flex items-center gap-2 px-3 py-2.5">
      <span
        class="h-2.5 w-2.5 rounded-full"
        :style="{ backgroundColor: column.color ?? 'var(--muted-foreground)' }"
      />
      <span class="truncate text-sm font-semibold">{{ column.name }}</span>
      <span class="text-xs text-muted-foreground">{{ cards.length }}</span>
      <span
        v-if="column.workflows.length"
        class="ml-auto inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
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
        v-for="card in cards"
        :key="card.id"
        data-board-card
      >
        <BoardCardItem
          :card="card"
          @open="emit('openCard', $event)"
        />
      </div>
    </div>
    <div class="flex items-center gap-1 border-t border-border/40 p-2">
      <Plus class="h-4 w-4 text-muted-foreground" />
      <input
        v-model="newCardTitle"
        type="text"
        placeholder="Add a card"
        class="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        @keydown.enter="addCard"
      >
    </div>
  </div>
</template>
