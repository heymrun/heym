import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRecentWorkflows } from "./useRecentWorkflows";

// Node has no `localStorage` global at all (confirmed: `typeof localStorage`
// is "undefined" in plain Node, same class of gap as window/document in
// useOverlayBackHandler's test file). This source calls `localStorage`
// directly as a bare identifier, so it needs a real fake, not a stub object
// with vi.fn() methods that don't actually store anything - the tests need
// genuine persistence between getRecent()/addRecent() calls within one test.
//
// A minimal fake Storage is enough - the source only ever calls
// getItem/setItem (never removeItem/clear/key/length).
class FakeStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
}

// `STORAGE_KEY` and `MAX_RECENT` are not exported - hardcoded here per the
// source's own current values.
const STORAGE_KEY = "heym_recent_workflows";
const MAX_RECENT = 2;

let storage: FakeStorage;

beforeEach(() => {
  // Rebuilt fresh every test - don't reuse one instance across tests, or one
  // test's leftover data leaks into the next.
  storage = new FakeStorage();
  vi.stubGlobal("localStorage", storage);
});

describe("getRecent", () => {
  it("returns an empty array when nothing has been stored", () => {
    const { getRecent } = useRecentWorkflows();
    expect(getRecent()).toEqual([]);
  });

  it("returns an empty array when the stored value is not valid JSON", () => {
    storage.setItem(STORAGE_KEY, "not valid json at all");
    const { getRecent } = useRecentWorkflows();
    expect(getRecent()).toEqual([]);
  });

  it("returns an empty array when the stored value is valid JSON but not an array", () => {
    storage.setItem(STORAGE_KEY, JSON.stringify({ not: "an array" }));
    const { getRecent } = useRecentWorkflows();
    expect(getRecent()).toEqual([]);
  });

  it("truncates to MAX_RECENT even if more entries were already stored", () => {
    const stale = [
      { id: "wf-1", name: "First" },
      { id: "wf-2", name: "Second" },
      { id: "wf-3", name: "Third" },
    ];
    storage.setItem(STORAGE_KEY, JSON.stringify(stale));
    const { getRecent } = useRecentWorkflows();

    expect(getRecent()).toEqual(stale.slice(0, MAX_RECENT));
  });
});

describe("addRecent", () => {
  it("adds a new workflow to recent and persists it", () => {
    const { addRecent, getRecent } = useRecentWorkflows();
    addRecent("wf-1", "First");

    expect(getRecent()).toEqual([{ id: "wf-1", name: "First" }]);
  });

  it("orders recent workflows most-recent-first", () => {
    const { addRecent, getRecent } = useRecentWorkflows();
    addRecent("wf-1", "First");
    addRecent("wf-2", "Second");

    expect(getRecent()).toEqual([
      { id: "wf-2", name: "Second" },
      { id: "wf-1", name: "First" },
    ]);
  });

  it("re-adding an existing workflow id moves it to the front instead of duplicating it", () => {
    // Deliberately only ONE workflow id, re-added, with no other entries in
    // play - with MAX_RECENT at 2, mixing in a second distinct workflow would
    // let `slice(0, MAX_RECENT)` coincidentally truncate away a leftover
    // un-deduped duplicate, passing this test even if the dedup filter were
    // removed entirely (caught by mutation-testing this exact scenario).
    // Isolating to one id makes the array length itself prove dedup ran.
    const { addRecent, getRecent } = useRecentWorkflows();
    addRecent("wf-1", "First");
    addRecent("wf-1", "First Renamed");

    expect(getRecent()).toEqual([{ id: "wf-1", name: "First Renamed" }]);
  });

  it("re-adding an existing workflow id among others moves it to the front", () => {
    const { addRecent, getRecent } = useRecentWorkflows();
    addRecent("wf-1", "First");
    addRecent("wf-2", "Second");
    addRecent("wf-1", "First Renamed");

    expect(getRecent()).toEqual([
      { id: "wf-1", name: "First Renamed" },
      { id: "wf-2", name: "Second" },
    ]);
  });

  it("keeps only the MAX_RECENT most recent workflows, dropping the oldest", () => {
    const { addRecent, getRecent } = useRecentWorkflows();
    addRecent("wf-1", "First");
    addRecent("wf-2", "Second");
    addRecent("wf-3", "Third");

    expect(getRecent()).toEqual([
      { id: "wf-3", name: "Third" },
      { id: "wf-2", name: "Second" },
    ]);
  });

  it("a storage write failure (e.g. quota exceeded) does not throw", () => {
    vi.spyOn(storage, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    const { addRecent } = useRecentWorkflows();

    expect(() => addRecent("wf-1", "First")).not.toThrow();
  });
});
