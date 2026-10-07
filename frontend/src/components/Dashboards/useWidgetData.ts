import { ref, type Ref } from "vue";

import type { ChartPayload } from "@/types/dashboard";
import { toggleTaskItemLocal, updateOrRemoveTaskItemLocal } from "@/lib/markdownTaskList";
import { dashboardApi } from "@/services/api";

export interface WidgetData {
  payload: Ref<ChartPayload | null>;
  loading: Ref<boolean>;
  error: Ref<string | null>;
  markdownTaskSaving: Ref<boolean>;
  loadData: (force?: boolean) => Promise<void>;
  toggleMarkdownTask: (lineIndex: number) => Promise<void>;
  updateMarkdownTask: (update: { lineIndex: number; text: string }) => Promise<void>;
}

/**
 * A widget's chart and its markdown checklist edits, loaded through the dashboards API.
 * `record` is the detail page's ?record= value, or null on the dashboard itself.
 */
export function useWidgetData(
  widgetId: () => string,
  record: () => string | null = () => null,
): WidgetData {
  const payload = ref<ChartPayload | null>(null);
  const loading = ref(true);
  const error = ref<string | null>(null);
  const markdownTaskSaving = ref(false);

  async function loadData(force = false): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const response = await dashboardApi.getWidgetData(widgetId(), force, record());
      payload.value = response.payload;
      error.value = response.error ?? null;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Failed to load widget";
    } finally {
      loading.value = false;
    }
  }

  async function toggleMarkdownTask(lineIndex: number): Promise<void> {
    if (!payload.value || payload.value.type !== "text" || !payload.value.text_interactive) {
      return;
    }
    const previousPayload = payload.value;
    const previousText = previousPayload.text ?? "";
    markdownTaskSaving.value = true;
    try {
      payload.value = {
        ...previousPayload,
        text: toggleTaskItemLocal(previousText, lineIndex),
      };
      const response = await dashboardApi.toggleMarkdownTask(widgetId(), lineIndex);
      payload.value = response.payload;
      error.value = response.error ?? null;
    } catch (e) {
      payload.value = previousPayload;
      error.value = e instanceof Error ? e.message : "Failed to update checkbox";
    } finally {
      markdownTaskSaving.value = false;
    }
  }

  async function updateMarkdownTask(update: { lineIndex: number; text: string }): Promise<void> {
    if (!payload.value || payload.value.type !== "text" || !payload.value.text_interactive) {
      return;
    }
    const previousPayload = payload.value;
    const previousText = previousPayload.text ?? "";
    markdownTaskSaving.value = true;
    try {
      payload.value = {
        ...previousPayload,
        text: updateOrRemoveTaskItemLocal(previousText, update.lineIndex, update.text),
      };
      const response = await dashboardApi.updateMarkdownTask(
        widgetId(),
        update.lineIndex,
        update.text,
      );
      payload.value = response.payload;
      error.value = response.error ?? null;
    } catch (e) {
      payload.value = previousPayload;
      error.value = e instanceof Error ? e.message : "Failed to update checkbox item";
    } finally {
      markdownTaskSaving.value = false;
    }
  }

  return {
    payload,
    loading,
    error,
    markdownTaskSaving,
    loadData,
    toggleMarkdownTask,
    updateMarkdownTask,
  };
}
