<script setup lang="ts">
import { ref } from "vue";
import { Plus } from "lucide-vue-next";

import { useBoardStore } from "@/stores/board";
import { boardApi } from "@/services/api";
import BoardColumnLane from "./BoardColumnLane.vue";

const emit = defineEmits<{
  (e: "openCard", cardId: string): void;
  (e: "openSettings", columnId: string): void;
}>();

const boardStore = useBoardStore();
const addingColumn = ref(false);
const newColumnName = ref("");

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
  <div class="flex h-full gap-3 overflow-x-auto p-4">
    <BoardColumnLane
      v-for="column in boardStore.activeBoard?.columns ?? []"
      :key="column.id"
      :column="column"
      @open-card="emit('openCard', $event)"
      @open-settings="emit('openSettings', $event)"
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
