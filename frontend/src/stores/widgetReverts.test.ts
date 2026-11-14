import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { parseChatWidgetChange } from "@/lib/chatWidgetChange";
import { useWidgetRevertsStore } from "@/stores/widgetReverts";

describe("parseChatWidgetChange", () => {
  it("reads a widget change and the snapshot before it", () => {
    expect(
      parseChatWidgetChange({
        type: "dashboard",
        action: "widget_updated",
        dashboard_id: "d1",
        widget_id: "w1",
        title: "Open cases",
        previous_version: 7,
      }),
    ).toEqual({ action: "widget_updated", dashboardId: "d1", widgetId: "w1", previousVersion: 7 });
  });

  it("keeps a change without a snapshot and drops anything else", () => {
    expect(
      parseChatWidgetChange({ type: "dashboard", action: "arranged", dashboard_id: "d1" }),
    ).toEqual({ action: "arranged", dashboardId: "d1", widgetId: null, previousVersion: null });
    expect(
      parseChatWidgetChange({
        type: "dashboard",
        action: "widget_updated",
        dashboard_id: "d1",
        widget_id: "w1",
        previous_version: "7",
      })?.previousVersion,
    ).toBeNull();
    expect(parseChatWidgetChange({ type: "dashboard", action: "widget_updated" })).toBeNull();
    expect(parseChatWidgetChange({ type: "content", text: "hi" })).toBeNull();
  });
});

describe("widget reverts store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("offers a revert for a chat change that names its snapshot", () => {
    const store = useWidgetRevertsStore();
    store.receive({ action: "widget_updated", dashboardId: "d1", widgetId: "w1", previousVersion: 7 });
    expect(store.offers).toEqual({ w1: 7 });
  });

  it("keeps the newest change's snapshot", () => {
    const store = useWidgetRevertsStore();
    store.receive({ action: "widget_updated", dashboardId: "d1", widgetId: "w1", previousVersion: 7 });
    store.receive({ action: "widget_updated", dashboardId: "d1", widgetId: "w1", previousVersion: 9 });
    expect(store.offers).toEqual({ w1: 9 });
  });

  it("ignores renames, new widgets and layout changes", () => {
    const store = useWidgetRevertsStore();
    store.receive({ action: "widget_updated", dashboardId: "d1", widgetId: "w1", previousVersion: null });
    store.receive({ action: "widget_added", dashboardId: "d1", widgetId: "w2", previousVersion: null });
    store.receive({ action: "arranged", dashboardId: "d1", widgetId: null, previousVersion: null });
    expect(store.offers).toEqual({});
  });

  it("drops the offer of a removed widget and after forget", () => {
    const store = useWidgetRevertsStore();
    store.offer("w1", 7);
    store.offer("w2", 3);
    store.receive({ action: "widget_removed", dashboardId: "d1", widgetId: "w1", previousVersion: null });
    expect(store.offers).toEqual({ w2: 3 });
    store.forget("w2");
    expect(store.offers).toEqual({});
  });
});
