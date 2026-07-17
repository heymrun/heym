<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Plus, Settings, SquareKanban, Trash2 } from "lucide-vue-next";

import ExecutionHistoryAllDialog from "@/components/Panels/ExecutionHistoryAllDialog.vue";
import Button from "@/components/ui/Button.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { useToast } from "@/composables/useToast";
import { boardApi } from "@/services/api";
import { useBoardStore } from "@/stores/board";
import BoardCanvas from "./BoardCanvas.vue";
import BoardCardDetailDialog from "./BoardCardDetailDialog.vue";
import BoardColumnSettingsDialog from "./BoardColumnSettingsDialog.vue";
import BoardCreateDialog from "./BoardCreateDialog.vue";
import BoardEditDialog from "./BoardEditDialog.vue";

const boardStore = useBoardStore();
const route = useRoute();
const router = useRouter();
const { showToast } = useToast();
const createOpen = ref(false);
const editOpen = ref(false);
const openCardId = ref<string | null>(null);
const settingsColumnId = ref<string | null>(null);
const historyOpen = ref(false);
const historyWorkflowId = ref<string | undefined>(undefined);

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
    historyOpen.value = false;
    historyWorkflowId.value = undefined;
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

async function openErrorHistory(cardId: string): Promise<void> {
  const boardId = boardStore.activeBoard?.id;
  if (!boardId) return;

  try {
    const detail = await boardApi.getCard(boardId, cardId);
    const failedRun = [...detail.runs].reverse().find(
      (run) => run.status === "failed" && run.workflow_id !== null,
    );
    if (!failedRun?.workflow_id) {
      showToast("No workflow error history is available for this card", "error");
      return;
    }

    openCardId.value = null;
    historyOpen.value = false;
    historyWorkflowId.value = failedRun.workflow_id;
    historyOpen.value = true;
  } catch {
    showToast("Failed to load card error history", "error");
  }
}

function closeErrorHistory(): void {
  historyOpen.value = false;
  historyWorkflowId.value = undefined;
}
</script>

<template>
  <div
    class="flex h-full w-full min-w-0 flex-col"
    data-testid="board-panel"
  >
    <!-- pt-0 so the title sits at the same height as the Workflows tab heading. -->
    <div
      class="flex flex-wrap items-center gap-x-2 gap-y-2 border-b border-border/60 pb-2.5 pt-0 sm:flex-nowrap sm:gap-3"
      data-testid="board-header"
    >
      <div class="mr-auto flex min-w-0 flex-1 flex-col sm:mr-0 sm:flex-initial sm:shrink">
        <h2 class="text-xl font-bold tracking-tight md:text-2xl">
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

      <!-- SearchableSelect's root is w-full, so its wrapper controls the responsive width. -->
      <div
        v-if="boardStore.boards.length"
        class="order-last w-full shrink-0 sm:order-none sm:ml-auto sm:w-auto sm:min-w-[200px]"
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
        class="shrink-0 px-3 sm:px-4"
        aria-label="New board"
        data-testid="board-new"
        @click="createOpen = true"
      >
        <Plus class="h-4 w-4 sm:mr-1" />
        <span>New<span class="hidden sm:inline"> board</span></span>
      </Button>
      <Button
        v-if="boardStore.isOwner"
        size="sm"
        variant="ghost"
        class="w-11 shrink-0 px-0 sm:w-auto sm:px-4"
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
        class="w-11 shrink-0 px-0 sm:w-auto sm:px-4"
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
      @open-error-history="openErrorHistory"
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
    <ExecutionHistoryAllDialog
      :open="historyOpen"
      :workflow-id="historyWorkflowId"
      initial-status="error"
      @close="closeErrorHistory"
    />
  </div>
</template>
