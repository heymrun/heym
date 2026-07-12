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
    <div class="w-64 shrink-0">
      <button
        v-if="!addingColumn"
        class="flex w-full items-center gap-2 rounded-xl border border-dashed border-border/60 px-3 py-2.5 text-sm text-muted-foreground hover:border-primary/50 hover:text-foreground"
        @click="addingColumn = true"
      >
        <Plus class="h-4 w-4" /> Add column
      </button>
      <div
        v-else
        class="rounded-xl border border-border/60 p-2"
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
