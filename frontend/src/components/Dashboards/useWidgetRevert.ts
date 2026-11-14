import { computed, ref, type ComputedRef, type Ref } from "vue";

import type { DashboardWidget } from "@/types/dashboard";

import { useToast } from "@/composables/useToast";
import { responseDetail } from "@/lib/responseDetail";
import { dashboardApi } from "@/services/api";
import { useDashboardStore } from "@/stores/dashboard";
import { useWidgetRevertsStore } from "@/stores/widgetReverts";

export interface WidgetRevert {
  /** Widgets on the dashboard whose last AI change can be undone. */
  revertibleIds: ComputedRef<string[]>;
  revertingId: Ref<string | null>;
  /** A fine-tune's answer names the snapshot from before it; offer to go back to it. */
  offerFromRefine: (widget: DashboardWidget) => void;
  revert: (widgetId: string) => Promise<void>;
}

/**
 * The Dashboard tab's "Revert previous": puts a widget back as it was before its last AI change,
 * from Chat or a fine-tune. Heym restores the snapshot only while it is the newest one, so a
 * change made since is never overwritten; the offer ends either way.
 */
export function useWidgetRevert(): WidgetRevert {
  const dashboardStore = useDashboardStore();
  const reverts = useWidgetRevertsStore();
  const { showToast } = useToast();
  const revertingId = ref<string | null>(null);

  const revertibleIds = computed((): string[] =>
    dashboardStore.widgets.filter((widget) => widget.id in reverts.offers).map((widget) => widget.id),
  );

  function offerFromRefine(widget: DashboardWidget): void {
    if (typeof widget.previous_version_number === "number") {
      reverts.offer(widget.id, widget.previous_version_number);
    } else {
      reverts.forget(widget.id);
    }
  }

  async function revert(widgetId: string): Promise<void> {
    const version = reverts.offers[widgetId];
    if (version === undefined || revertingId.value !== null) return;
    revertingId.value = widgetId;
    try {
      const widget = await dashboardApi.revertWidget(widgetId, version);
      dashboardStore.replaceWidget(widget);
      showToast(`Reverted ${widget.title}.`, "success");
    } catch (error: unknown) {
      showToast(responseDetail(error) ?? "The widget could not be reverted.", "error");
    } finally {
      reverts.forget(widgetId);
      revertingId.value = null;
    }
  }

  return { revertibleIds, revertingId, offerFromRefine, revert };
}
