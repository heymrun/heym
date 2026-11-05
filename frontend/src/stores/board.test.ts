import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import type { BoardCard, BoardState } from "@/types/board";

vi.mock("@/services/api", () => ({
  boardApi: {
    getState: vi.fn(),
    members: vi.fn(),
    revision: vi.fn(),
    moveCard: vi.fn(),
  },
}));

import { emptyCardFields } from "@/lib/boardCardFields";
import { boardApi } from "@/services/api";
import { useBoardStore } from "@/stores/board";

function card(id: string, columnId: string, position: number, updatedAt: string): BoardCard {
  return {
    id,
    board_id: "b",
    column_id: columnId,
    title: id,
    content: "",
    position,
    run_status: "idle",
    card_metadata: {},
    fields: emptyCardFields(),
    edit_version: "v",
    created_at: updatedAt,
    updated_at: updatedAt,
  };
}

function board(cards: BoardCard[]): BoardState {
  return {
    id: "b",
    name: "Legal",
    description: null,
    mapper_model: null,
    mapper_credential_id: null,
    mapper_credential_name: null,
    permission: "owner",
    auto_advance: false,
    columns: [
      { id: "todo", board_id: "b", name: "To do", position: 0, color: null, ai_instructions: null, workflows: [] },
      { id: "done", board_id: "b", name: "Done", position: 1, color: null, ai_instructions: null, workflows: [] },
    ],
    cards,
    has_active_runs: false,
  };
}

describe("board store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(boardApi.getState).mockReset();
    vi.mocked(boardApi.members).mockReset().mockResolvedValue([]);
    vi.mocked(boardApi.revision).mockReset().mockResolvedValue("r0");
    vi.mocked(boardApi.moveCard).mockReset();
  });

  it("orders each column by position, not by when a card last changed", async () => {
    vi.mocked(boardApi.getState).mockResolvedValue(
      board([
        card("a", "todo", 1, "2026-11-05T10:00:00Z"),
        card("b", "todo", 0, "2026-11-01T10:00:00Z"),
      ]),
    );
    const store = useBoardStore();
    await store.openBoard("b");
    expect(store.cardsByColumn.todo.map((c) => c.id)).toEqual(["b", "a"]);
    store.stopPolling();
  });

  it("loads the board's members with the board", async () => {
    vi.mocked(boardApi.getState).mockResolvedValue(board([]));
    vi.mocked(boardApi.members).mockResolvedValue([
      { user_id: "u1", name: "Ada", email: "ada@example.com", permission: "owner" },
    ]);
    const store = useBoardStore();
    await store.openBoard("b");
    expect(store.members.map((m) => m.name)).toEqual(["Ada"]);
    store.stopPolling();
  });

  it("sends the slot among the other cards when a card moves down its own column", async () => {
    const cards = [
      card("a", "todo", 0, "2026-11-05T10:00:00Z"),
      card("b", "todo", 1, "2026-11-05T10:00:00Z"),
      card("c", "todo", 2, "2026-11-05T10:00:00Z"),
    ];
    vi.mocked(boardApi.getState).mockResolvedValue(board(cards));
    const store = useBoardStore();
    await store.openBoard("b");
    // Dropped below "c": the drop index counts "a" itself, so it is 3.
    await store.moveCard("a", "todo", 3);
    expect(vi.mocked(boardApi.moveCard).mock.calls[0][2]).toEqual({ to_column_id: "todo", position: 2 });
    await store.moveCard("c", "done", 0);
    expect(vi.mocked(boardApi.moveCard).mock.calls[1][2]).toEqual({ to_column_id: "done", position: 0 });
    store.stopPolling();
  });

  it("reloads the board only when its revision changes", async () => {
    vi.mocked(boardApi.getState).mockResolvedValue(board([]));
    // Read before the state on open, so a change between the two reads still shows up.
    vi.mocked(boardApi.revision).mockResolvedValueOnce("r1").mockResolvedValueOnce("r1").mockResolvedValueOnce("r2");
    const store = useBoardStore();
    await store.openBoard("b");
    await store.checkRevision();
    expect(boardApi.getState).toHaveBeenCalledTimes(1);
    await store.checkRevision();
    expect(boardApi.getState).toHaveBeenCalledTimes(2);
    store.stopPolling();
  });
});
