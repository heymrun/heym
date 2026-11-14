import { ref } from "vue";
import { defineStore } from "pinia";

import type { ChatWidgetChange } from "@/types/dashboard";

/**
 * Widgets whose last AI change, from Chat or a widget's fine-tune, can be undone, with the Edit
 * History snapshot Heym stored before it. Nothing is kept: a reload, a revert or a newer
 * change ends the offer, and Heym refuses a snapshot that is no longer the newest one.
 */
export const useWidgetRevertsStore = defineStore("widgetReverts", () => {
  const offers = ref<Record<string, number>>({});

  function offer(widgetId: string, version: number): void {
    offers.value = { ...offers.value, [widgetId]: version };
  }

  function forget(widgetId: string): void {
    if (!(widgetId in offers.value)) return;
    offers.value = Object.fromEntries(
      Object.entries(offers.value).filter(([id]) => id !== widgetId),
    );
  }

  /** A chat turn's widget change; a change that names its snapshot can be reverted. */
  function receive(change: ChatWidgetChange): void {
    if (!change.widgetId) return;
    if (change.action === "widget_removed") {
      forget(change.widgetId);
    } else if (change.action === "widget_updated" && change.previousVersion !== null) {
      offer(change.widgetId, change.previousVersion);
    }
  }

  return { offers, offer, forget, receive };
});
