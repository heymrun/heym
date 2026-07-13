<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Plus, Settings, SquareKanban, Trash2 } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { useBoardStore } from "@/stores/board";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import BoardCanvas from "./BoardCanvas.vue";
import BoardCardDetailDialog from "./BoardCardDetailDialog.vue";
import BoardColumnSettingsDialog from "./BoardColumnSettingsDialog.vue";
import BoardCreateDialog from "./BoardCreateDialog.vue";
import BoardEditDialog from "./BoardEditDialog.vue";

const boardStore = useBoardStore();
const route = useRoute();
const router = useRouter();
const createOpen = ref(false);
const editOpen = ref(false);
const openCardId = ref<string | null>(null);
const settingsColumnId = ref<string | null>(null);

async function openBoardWithUrl(boardId: string): Promise<void> {
  await boardStore.openBoard(boardId);
  if (route.query.board !== boardId) {
    await router.replace({ query: { ...route.query, tab: "board", board: boardId } });
  }
}

// The app's global Escape handler dispatches a dismiss-overlays event (and
// preventDefaults, which defeats each Dialog's own Esc handler), so overlays
// close by subscribing here.
let removeOverlayDismiss: (() => void) | null = null;

onMounted(async () => {
  removeOverlayDismiss = onDismissOverlays(() => {
    createOpen.value = false;
    editOpen.value = false;
    openCardId.value = null;
    settingsColumnId.value = null;
  });
  await boardStore.fetchBoards();
  const urlBoardId = typeof route.query.board === "string" ? route.query.board : null;
  const target =
    urlBoardId && boardStore.boards.some((b) => b.id === urlBoardId)
      ? urlBoardId
      : boardStore.boards[0]?.id;
  if (target) await openBoardWithUrl(target);
});

onUnmounted(() => {
  boardStore.stopPolling();
  removeOverlayDismiss?.();
});

const boardOptions = computed(() =>
  boardStore.boards.map((board) => ({ value: board.id, label: board.name })),
);

async function selectBoard(boardId: string | undefined): Promise<void> {
  if (boardId) await openBoardWithUrl(boardId);
}

async function removeActiveBoard(): Promise<void> {
  const board = boardStore.activeBoard;
  if (!board) return;
  if (!window.confirm(`Delete board "${board.name}" and all of its cards?`)) return;
  await boardStore.deleteBoard(board.id);
  if (boardStore.boards.length > 0) {
    await openBoardWithUrl(boardStore.boards[0].id);
  } else {
    const query = { ...route.query };
    delete query.board;
    await router.replace({ query });
  }
}

async function onBoardCreated(boardId: string): Promise<void> {
  await openBoardWithUrl(boardId);
}
</script>

<template>
  <div
    class="flex h-full flex-col"
    data-testid="board-panel"
  >
    <!-- pt-0 so the title sits at the same height as the Workflows tab heading. -->
    <div class="flex items-center gap-3 border-b border-border/60 pb-2.5 pt-0">
      <div class="flex min-w-0 shrink flex-col">
        <h2 class="text-xl md:text-2xl font-bold tracking-tight">
          Board
        </h2>
        <p
          v-if="boardStore.activeBoard?.description"
          class="truncate text-xs text-muted-foreground"
          :title="boardStore.activeBoard.description"
          data-testid="board-description"
        >
          {{ boardStore.activeBoard.description }}
        </p>
      </div>

      <!-- SearchableSelect's root is w-full, so it needs a fixed-width wrapper. -->
      <div
        v-if="boardStore.boards.length"
        class="ml-auto w-56 shrink-0"
      >
        <!-- Keyed on the name: the combobox caches its display value, so a rename only
             shows up if the select is rebuilt. -->
        <SearchableSelect
          :key="boardStore.activeBoard?.name ?? ''"
          :model-value="boardStore.activeBoard?.id ?? ''"
          :options="boardOptions"
          placeholder="Select board"
          search-placeholder="Search boards…"
          aria-label="Select board"
          @update:model-value="selectBoard"
        />
      </div>
      <Button
        size="sm"
        variant="outline"
        class="shrink-0"
        data-testid="board-new"
        @click="createOpen = true"
      >
        <Plus class="mr-1 h-4 w-4" /> New board
      </Button>
      <Button
        v-if="boardStore.isOwner"
        size="sm"
        variant="ghost"
        class="shrink-0"
        aria-label="Board settings"
        title="Board settings"
        data-testid="board-edit"
        @click="editOpen = true"
      >
        <Settings class="h-4 w-4 text-muted-foreground" />
      </Button>
      <Button
        v-if="boardStore.isOwner"
        size="sm"
        variant="ghost"
        class="shrink-0"
        aria-label="Delete board"
        @click="removeActiveBoard"
      >
        <Trash2 class="h-4 w-4 text-muted-foreground" />
      </Button>
    </div>

    <div
      v-if="!boardStore.loading && boardStore.boards.length === 0"
      class="flex flex-1 flex-col items-center justify-start gap-3 px-4 pt-16 text-center"
    >
      <SquareKanban class="h-10 w-10 text-muted-foreground" />
      <p class="max-w-md text-sm text-muted-foreground">
        No boards yet. Cards are agentic jobs — moving one into a column runs that column's
        workflows with the card's full context.
      </p>
      <Button
        data-testid="board-empty-create"
        @click="createOpen = true"
      >
        Create your first board
      </Button>
    </div>

    <BoardCanvas
      v-else-if="boardStore.activeBoard"
      @open-card="openCardId = $event"
      @open-settings="settingsColumnId = $event"
    />

    <BoardCreateDialog
      :open="createOpen"
      @close="createOpen = false"
      @created="onBoardCreated"
    />
    <BoardEditDialog
      :open="editOpen"
      @close="editOpen = false"
    />
    <BoardCardDetailDialog
      :open="openCardId !== null"
      :card-id="openCardId"
      @close="openCardId = null"
    />
    <BoardColumnSettingsDialog
      :open="settingsColumnId !== null"
      :column-id="settingsColumnId"
      @close="settingsColumnId = null"
    />
  </div>
</template>
