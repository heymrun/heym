import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRenderer, nextTick, ref, type App, type Ref } from "vue";

import { useRunPanelFileDrag } from "./useRunPanelFileDrag";

// This source calls onUnmounted() directly - a COMPONENT lifecycle hook, not
// onScopeDispose. A bare effectScope() silently no-ops the registration (Vue
// only warns in dev), so calling useRunPanelFileDrag(disabled) at the top
// level of a test body would never actually run its cleanup. Build a real,
// DOM-less component with a no-op custom renderer instead (every host
// operation a no-op - no jsdom needed), the same approach used for
// useWorkflowRowStatus.test.ts and useOverlayBackHandler.test.ts.
const { createApp } = createRenderer<object, object>({
  createElement: () => ({}),
  insert: () => {},
  remove: () => {},
  setElementText: () => {},
  createText: () => ({}),
  createComment: () => ({}),
  setText: () => {},
  patchProp: () => {},
  parentNode: () => null,
  nextSibling: () => null,
});

let trackedApps: App[] = [];

function mountDrag(disabled: Ref<boolean>): ReturnType<typeof useRunPanelFileDrag> {
  let api!: ReturnType<typeof useRunPanelFileDrag>;
  const app = createApp({
    setup() {
      api = useRunPanelFileDrag(disabled);
      return () => null;
    },
  });
  app.mount({});
  trackedApps.push(app);
  return api;
}

// `document.addEventListener("dragend", onDocumentDragEnd, true)` uses the
// CAPTURE-phase boolean form - Node's native EventTarget has a confirmed real
// gap where `removeEventListener(type, fn, true)` (boolean form) can fail to
// match a listener added the same way, while `{ capture: true }` works (see
// useOverlayBackHandler.test.ts's FakeWindow for the original repro). This
// fake tracks listeners itself instead of relying on Node's EventTarget, so
// both capture argument forms match correctly for removal.
type Listener = (event: Event) => void;

class FakeDocument {
  private readonly listeners = new Map<string, Set<{ fn: Listener; capture: boolean }>>();

  addEventListener(type: string, fn: Listener, options?: boolean | { capture?: boolean }): void {
    const capture = typeof options === "boolean" ? options : Boolean(options?.capture);
    const set = this.listeners.get(type) ?? new Set();
    set.add({ fn, capture });
    this.listeners.set(type, set);
  }

  removeEventListener(
    type: string,
    fn: Listener,
    options?: boolean | { capture?: boolean },
  ): void {
    const capture = typeof options === "boolean" ? options : Boolean(options?.capture);
    const set = this.listeners.get(type);
    if (!set) return;
    for (const entry of set) {
      if (entry.fn === fn && entry.capture === capture) set.delete(entry);
    }
  }

  dispatchEvent(event: Event): boolean {
    const set = this.listeners.get(event.type);
    if (set) {
      for (const entry of [...set]) entry.fn(event);
    }
    return true;
  }
}

let fakeDocument: FakeDocument;

beforeEach(() => {
  fakeDocument = new FakeDocument();
  vi.stubGlobal("document", fakeDocument);
});

afterEach(() => {
  for (const app of trackedApps) {
    app.unmount();
  }
  trackedApps = [];
  vi.unstubAllGlobals();
});

interface DragEventOverrides {
  types?: string[];
  currentTarget?: { contains: (node: unknown) => boolean };
  relatedTarget?: unknown;
}

function buildDragEvent(overrides: DragEventOverrides = {}): DragEvent {
  const dataTransfer = overrides.types
    ? { types: overrides.types, dropEffect: "none" }
    : null;
  return {
    dataTransfer,
    preventDefault: () => {},
    currentTarget: overrides.currentTarget ?? { contains: () => false },
    relatedTarget: overrides.relatedTarget ?? null,
  } as unknown as DragEvent;
}

describe("onDragEnter / onDragOver", () => {
  it("activates on a file drag when not disabled", () => {
    const disabled = ref(false);
    const { isActive, onDragEnter } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["Files"] }));

    expect(isActive.value).toBe(true);
  });

  it("does nothing when disabled, even for a file drag", () => {
    const disabled = ref(true);
    const { isActive, onDragEnter } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["Files"] }));

    expect(isActive.value).toBe(false);
  });

  it("ignores a non-file drag (no Files type on dataTransfer)", () => {
    const disabled = ref(false);
    const { isActive, onDragEnter } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["text/plain"] }));

    expect(isActive.value).toBe(false);
  });
});

describe("onDragLeave", () => {
  it("deactivates after a single enter/leave pair", () => {
    const disabled = ref(false);
    const { isActive, onDragEnter, onDragLeave } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["Files"] }));
    onDragLeave(buildDragEvent());

    expect(isActive.value).toBe(false);
  });

  it("requires a matching number of leaves to deactivate after multiple enters", () => {
    const disabled = ref(false);
    const { isActive, onDragEnter, onDragLeave } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["Files"] }));
    onDragEnter(buildDragEvent({ types: ["Files"] }));
    onDragLeave(buildDragEvent());

    expect(isActive.value).toBe(true);

    onDragLeave(buildDragEvent());

    expect(isActive.value).toBe(false);
  });

  it("does not deactivate when the drag moves to a child element within the same container", () => {
    const disabled = ref(false);
    const { isActive, onDragEnter, onDragLeave } = mountDrag(disabled);
    const childNode = {};
    const container = { contains: (node: unknown) => node === childNode };

    onDragEnter(buildDragEvent({ types: ["Files"] }));
    onDragLeave(buildDragEvent({ currentTarget: container, relatedTarget: childNode }));

    expect(isActive.value).toBe(true);
  });
});

describe("onDragOver", () => {
  it("sets dropEffect to copy and activates for a file drag", () => {
    const disabled = ref(false);
    const { isActive, onDragOver } = mountDrag(disabled);
    const event = buildDragEvent({ types: ["Files"] });

    onDragOver(event);

    expect(event.dataTransfer?.dropEffect).toBe("copy");
    expect(isActive.value).toBe(true);
  });

  it("does nothing when disabled", () => {
    const disabled = ref(true);
    const { isActive, onDragOver } = mountDrag(disabled);

    onDragOver(buildDragEvent({ types: ["Files"] }));

    expect(isActive.value).toBe(false);
  });
});

describe("onDrop", () => {
  it("always resets drag state on drop, even when disabled", () => {
    const disabled = ref(true);
    const { isActive, onDrop } = mountDrag(disabled);

    onDrop(buildDragEvent());

    expect(isActive.value).toBe(false);
  });
});

describe("reset", () => {
  it("resets isActive and the internal drag counter", () => {
    const disabled = ref(false);
    const { isActive, onDragEnter, onDragLeave, reset } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["Files"] }));
    onDragEnter(buildDragEvent({ types: ["Files"] }));
    reset();

    expect(isActive.value).toBe(false);

    // If the counter weren't zeroed by reset(), a single leave here would
    // leave it at 1 (still > 0) rather than making it negative/no-op - this
    // just confirms a subsequent single enter/leave behaves like a fresh
    // start, not like two pending enters were still on the books.
    onDragEnter(buildDragEvent({ types: ["Files"] }));
    onDragLeave(buildDragEvent());

    expect(isActive.value).toBe(false);
  });
});

describe("document dragend listener wiring", () => {
  it("a global dragend event resets drag state while active", async () => {
    const disabled = ref(false);
    const { isActive, onDragEnter } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["Files"] }));
    await nextTick();
    expect(isActive.value).toBe(true);

    document.dispatchEvent(new Event("dragend"));

    expect(isActive.value).toBe(false);
  });

  it("does nothing on dragend before any drag has started", () => {
    const disabled = ref(false);
    const { isActive } = mountDrag(disabled);

    expect(() => document.dispatchEvent(new Event("dragend"))).not.toThrow();
    expect(isActive.value).toBe(false);
  });

  it("removes the document dragend listener once isActive goes back to false", async () => {
    const removeSpy = vi.spyOn(fakeDocument, "removeEventListener");
    const disabled = ref(false);
    const { onDragEnter, onDrop } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["Files"] }));
    await nextTick();
    onDrop(buildDragEvent());
    await nextTick();

    expect(removeSpy).toHaveBeenCalledWith("dragend", expect.any(Function), true);
  });

  it("removes the dragend listener on unmount even if a drag was still active", async () => {
    const removeSpy = vi.spyOn(fakeDocument, "removeEventListener");
    const disabled = ref(false);
    const { onDragEnter } = mountDrag(disabled);

    onDragEnter(buildDragEvent({ types: ["Files"] }));
    await nextTick();

    for (const app of trackedApps) {
      app.unmount();
    }
    trackedApps = [];

    expect(removeSpy).toHaveBeenCalledWith("dragend", expect.any(Function), true);
  });
});
