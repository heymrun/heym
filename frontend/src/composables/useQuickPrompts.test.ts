import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useQuickPrompts } from "./useQuickPrompts";
import { chatApi } from "@/services/api";
import { useChatStore } from "@/stores/chat";

// This composable reads/writes a REAL Pinia store (useChatStore), not a mock
// - same convention as this repo's other store-dependent component tests
// (see QuickWorkflowRunPanel.test.ts). A fresh Pinia instance per test avoids
// state leaking between tests via the store's own module-level registry.
// commitEdit() calls chatStore.saveQuickPrompts(), which internally calls the
// REAL chatApi.saveQuickPrompts() (a network call) - that's the one thing
// that needs mocking, at the chatApi boundary, not the whole store.

// Node has no KeyboardEvent global - build a plain Event and graft on `key`,
// same technique as useOverlayBackHandler.test.ts.
function buildKeydownEvent(key: string): KeyboardEvent {
  const event = new Event("keydown", { cancelable: true });
  Object.defineProperty(event, "key", { value: key, configurable: true });
  return event as unknown as KeyboardEvent;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.spyOn(chatApi, "saveQuickPrompts").mockImplementation((prompts: string[]) =>
    Promise.resolve(prompts),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("startEdit", () => {
  it("populates editingIndex and editingValue from the store's current prompts", () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["First prompt", "Second prompt"];
    const { startEdit, editingIndex, editingValue } = useQuickPrompts();

    startEdit(1);

    expect(editingIndex.value).toBe(1);
    expect(editingValue.value).toBe("Second prompt");
  });

  it("falls back to an empty string for an out-of-range index", () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["Only one"];
    const { startEdit, editingValue } = useQuickPrompts();

    startEdit(5);

    expect(editingValue.value).toBe("");
  });
});

describe("cancelEdit", () => {
  it("resets editingIndex to null and editingValue to empty", () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["First prompt"];
    const { startEdit, cancelEdit, editingIndex, editingValue } = useQuickPrompts();

    startEdit(0);
    cancelEdit();

    expect(editingIndex.value).toBeNull();
    expect(editingValue.value).toBe("");
  });
});

describe("commitEdit", () => {
  it("does nothing when there is no active edit", async () => {
    const { commitEdit } = useQuickPrompts();

    await commitEdit();

    expect(chatApi.saveQuickPrompts).not.toHaveBeenCalled();
  });

  it("cancels the edit without saving when the trimmed value is blank", async () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["First prompt"];
    const { startEdit, commitEdit, editingValue, editingIndex } = useQuickPrompts();

    startEdit(0);
    editingValue.value = "   ";
    await commitEdit();

    expect(chatApi.saveQuickPrompts).not.toHaveBeenCalled();
    expect(editingIndex.value).toBeNull();
  });

  it("saves the trimmed value at the edited index and clears the edit state", async () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["First prompt", "Second prompt"];
    const { startEdit, commitEdit, editingValue, editingIndex } = useQuickPrompts();

    startEdit(0);
    editingValue.value = "  Updated prompt  ";
    await commitEdit();

    expect(chatApi.saveQuickPrompts).toHaveBeenCalledWith(["Updated prompt", "Second prompt"]);
    expect(editingIndex.value).toBeNull();
    expect(editingValue.value).toBe("");
  });

  it("clears the edit state before the save resolves, not after", async () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["First prompt"];
    let resolveSave!: (value: string[]) => void;
    vi.mocked(chatApi.saveQuickPrompts).mockReturnValue(
      new Promise((resolve) => {
        resolveSave = resolve;
      }),
    );
    const { startEdit, commitEdit, editingValue, editingIndex } = useQuickPrompts();

    startEdit(0);
    editingValue.value = "Updated";
    const pending = commitEdit();

    // Edit state clears synchronously/optimistically, before the save
    // promise has settled.
    expect(editingIndex.value).toBeNull();

    resolveSave(["Updated"]);
    await pending;
  });
});

describe("onEditKeydown", () => {
  it("Enter commits the edit and prevents the default action", () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["First prompt"];
    const { startEdit, onEditKeydown, editingValue } = useQuickPrompts();
    startEdit(0);
    editingValue.value = "Updated";

    const event = buildKeydownEvent("Enter");
    const preventDefaultSpy = vi.spyOn(event, "preventDefault");
    onEditKeydown(event);

    expect(preventDefaultSpy).toHaveBeenCalledTimes(1);
  });

  it("Escape cancels the edit", () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["First prompt"];
    const { startEdit, onEditKeydown, editingIndex } = useQuickPrompts();
    startEdit(0);

    onEditKeydown(buildKeydownEvent("Escape"));

    expect(editingIndex.value).toBeNull();
  });

  it("other keys do nothing", () => {
    const chatStore = useChatStore();
    chatStore.quickPrompts = ["First prompt"];
    const { startEdit, onEditKeydown, editingIndex, editingValue } = useQuickPrompts();
    startEdit(0);

    onEditKeydown(buildKeydownEvent("a"));

    expect(editingIndex.value).toBe(0);
    expect(editingValue.value).toBe("First prompt");
    expect(chatApi.saveQuickPrompts).not.toHaveBeenCalled();
  });
});
