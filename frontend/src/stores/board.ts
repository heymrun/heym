import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type {
  BoardCard,
  BoardCreatePayload,
  BoardState,
  BoardSummary,
  BoardUpdatePayload,
  CardUpdatePayload,
} from "@/types/board";
import { boardApi } from "@/services/api";

const POLL_INTERVAL_MS = 2500;

export const useBoardStore = defineStore("board", () => {
  const boards = ref<BoardSummary[]>([]);
  const activeBoard = ref<BoardState | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  // The agentic model is mandatory: board actions stay disabled until it is chosen.
  const mapperConfigured = computed<boolean>(() =>
    Boolean(activeBoard.value?.mapper_credential_id && activeBoard.value?.mapper_model),
  );
  // A board shared read-only can be viewed but not changed; only its owner can open the
  // board settings (name, model, sharing) or delete it.
  const canWrite = computed<boolean>(() => activeBoard.value?.permission !== "read");
  const isOwner = computed<boolean>(() => activeBoard.value?.permission === "owner");

  const cardsByColumn = computed<Record<string, BoardCard[]>>(() => {
    const grouped: Record<string, BoardCard[]> = {};
    if (!activeBoard.value) return grouped;
    for (const column of activeBoard.value.columns) grouped[column.id] = [];
    for (const card of activeBoard.value.cards) {
      (grouped[card.column_id] ??= []).push(card);
    }
    for (const columnId of Object.keys(grouped)) {
      grouped[columnId].sort((a, b) => a.position - b.position);
    }
    return grouped;
  });

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function syncPolling(): void {
    const shouldPoll = activeBoard.value?.has_active_runs ?? false;
    if (shouldPoll && pollTimer === null) {
      pollTimer = setInterval(() => {
        void refreshActiveBoard();
      }, POLL_INTERVAL_MS);
    } else if (!shouldPoll) {
      stopPolling();
    }
  }

  async function fetchBoards(): Promise<void> {
    loading.value = true;
    try {
      boards.value = await boardApi.list();
      error.value = null;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to load boards";
    } finally {
      loading.value = false;
    }
  }

  async function openBoard(boardId: string): Promise<void> {
    loading.value = true;
    try {
      activeBoard.value = await boardApi.getState(boardId);
      error.value = null;
      syncPolling();
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to load board";
    } finally {
      loading.value = false;
    }
  }

  async function refreshActiveBoard(): Promise<void> {
    if (!activeBoard.value) return;
    try {
      activeBoard.value = await boardApi.getState(activeBoard.value.id);
      syncPolling();
    } catch {
      stopPolling();
    }
  }

  async function createBoard(payload: BoardCreatePayload): Promise<BoardSummary> {
    const board = await boardApi.create(payload);
    await fetchBoards();
    return board;
  }

  async function updateBoard(boardId: string, payload: BoardUpdatePayload): Promise<void> {
    await boardApi.update(boardId, payload);
    await fetchBoards();
    if (activeBoard.value?.id === boardId) await refreshActiveBoard();
  }

  async function deleteBoard(boardId: string): Promise<void> {
    await boardApi.remove(boardId);
    if (activeBoard.value?.id === boardId) {
      activeBoard.value = null;
      stopPolling();
    }
    await fetchBoards();
  }

  async function moveColumn(columnId: string, toIndex: number): Promise<void> {
    const board = activeBoard.value;
    if (!board) return;
    await boardApi.updateColumn(board.id, columnId, { position: toIndex });
    await refreshActiveBoard();
  }

  async function createCard(title: string, columnId?: string): Promise<void> {
    if (!activeBoard.value) return;
    await boardApi.createCard(activeBoard.value.id, { title, column_id: columnId });
    await refreshActiveBoard();
  }

  async function moveCard(cardId: string, toColumnId: string, position: number): Promise<void> {
    const board = activeBoard.value;
    if (!board) return;
    const card = board.cards.find((c) => c.id === cardId);
    if (!card) return;
    const previous = { column_id: card.column_id, position: card.position };
    card.column_id = toColumnId;
    card.position = position - 0.5; // optimistic slot between neighbors
    try {
      await boardApi.moveCard(board.id, cardId, { to_column_id: toColumnId, position });
      await refreshActiveBoard();
    } catch (err) {
      card.column_id = previous.column_id;
      card.position = previous.position;
      error.value = err instanceof Error ? err.message : "Move failed";
    }
  }

  async function updateCard(cardId: string, payload: CardUpdatePayload): Promise<void> {
    const board = activeBoard.value;
    if (!board) return;
    try {
      const updatedCard = await boardApi.updateCard(board.id, cardId, payload);
      const cardIndex = board.cards.findIndex((card) => card.id === cardId);
      if (cardIndex !== -1) board.cards[cardIndex] = updatedCard;
      error.value = null;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to update card";
      throw err;
    }
  }

  async function runFollowUp(cardId: string): Promise<void> {
    if (!activeBoard.value) return;
    await boardApi.runCard(activeBoard.value.id, cardId);
    await refreshActiveBoard();
  }

  async function deleteCard(cardId: string): Promise<void> {
    if (!activeBoard.value) return;
    await boardApi.deleteCard(activeBoard.value.id, cardId);
    await refreshActiveBoard();
  }

  async function cloneCard(cardId: string): Promise<void> {
    const board = activeBoard.value;
    if (!board) return;
    const card = board.cards.find((c) => c.id === cardId);
    if (!card) return;
    await boardApi.createCard(board.id, {
      title: card.title,
      content: card.content,
      column_id: card.column_id,
    });
    await refreshActiveBoard();
  }

  return {
    boards,
    activeBoard,
    loading,
    error,
    cardsByColumn,
    mapperConfigured,
    canWrite,
    isOwner,
    fetchBoards,
    openBoard,
    refreshActiveBoard,
    createBoard,
    updateBoard,
    deleteBoard,
    moveColumn,
    createCard,
    updateCard,
    moveCard,
    runFollowUp,
    deleteCard,
    cloneCard,
    stopPolling,
  };
});
