<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Plus } from "lucide-vue-next";

import { useBoardStore } from "@/stores/board";
import { boardApi } from "@/services/api";
import BoardColumnLane from "./BoardColumnLane.vue";

const emit = defineEmits<{
  (e: "openCard", cardId: string): void;
  (e: "openSettings", columnId: string): void;
  (e: "openErrorHistory", cardId: string): void;
}>();

const boardStore = useBoardStore();
const addingColumn = ref(false);
const newColumnName = ref("");
const canvas = ref<HTMLElement | null>(null);
const availableHeight = ref<number | null>(null);

function updateAvailableHeight(): void {
  const element = canvas.value;
  if (!element) return;
  const main = element.closest("main");
  const bottomSpacing = main
    ? Number.parseFloat(window.getComputedStyle(main).paddingBottom) || 0
    : 0;
  availableHeight.value = Math.max(
    0,
    window.innerHeight - element.getBoundingClientRect().top - bottomSpacing,
  );
}

onMounted(() => {
  updateAvailableHeight();
  window.addEventListener("resize", updateAvailableHeight);
});

onUnmounted(() => {
  window.removeEventListener("resize", updateAvailableHeight);
});

watch(
  () => boardStore.activeBoard?.description,
  async () => {
    await nextTick();
    updateAvailableHeight();
  },
);

async function addColumn(): Promise<void> {
  const name = newColumnName.value.trim();
  const board = boardStore.activeBoard;
  if (!name || !board) return;
  await boardApi.createColumn(board.id, { name });
  newColumnName.value = "";
  addingColumn.value = false;
  await boardStore.refreshActiveBoard();
}
</script>

<template>
  <div
    ref="canvas"
    class="flex min-h-0 gap-3 overflow-x-auto p-4"
    :style="availableHeight === null ? undefined : { height: `${availableHeight}px` }"
    data-testid="board-canvas"
  >
    <BoardColumnLane
      v-for="(column, index) in boardStore.activeBoard?.columns ?? []"
      :key="column.id"
      class="lane-enter"
      :style="{ animationDelay: `${index * 60}ms` }"
      :column="column"
      :index="index"
      @open-card="emit('openCard', $event)"
      @open-settings="emit('openSettings', $event)"
      @open-error-history="emit('openErrorHistory', $event)"
    />
    <div class="flex w-64 shrink-0 flex-col">
      <button
        v-if="!addingColumn"
        class="flex h-full w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border/60 p-4 text-sm text-muted-foreground hover:border-primary/50 hover:text-foreground"
        @click="addingColumn = true"
      >
        <Plus class="h-5 w-5" />
        <span>Add column</span>
      </button>
      <div
        v-else
        class="h-full rounded-xl border border-border/60 p-2"
      >
        <input
          v-model="newColumnName"
          type="text"
          placeholder="Column name"
          class="w-full bg-transparent text-sm outline-none"
          @keydown.enter="addColumn"
          @keydown.esc="addingColumn = false"
        >
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Staggered entrance, once per mount (board open or switch) — polling reuses the nodes. */
.lane-enter {
  animation: lane-enter 0.38s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes lane-enter {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
