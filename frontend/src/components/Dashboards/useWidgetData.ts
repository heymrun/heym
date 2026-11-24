import { ref, type Ref } from "vue";

import type { ChartPayload, FileRunPayload, RunWidgetAction, WidgetActionEvent } from "@/types/dashboard";
import { toggleTaskItemLocal, updateOrRemoveTaskItemLocal } from "@/lib/markdownTaskList";
import { dashboardApi, getErrorDetail } from "@/services/api";

export interface WidgetData {
  payload: Ref<ChartPayload | FileRunPayload | null>;
  loading: Ref<boolean>;
  error: Ref<string | null>;
  markdownTaskSaving: Ref<boolean>;
  loadData: (force?: boolean) => Promise<void>;
  runHtmlAction: RunWidgetAction;
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
  const payload = ref<ChartPayload | FileRunPayload | null>(null);
  const loading = ref(true);
  const error = ref<string | null>(null);
  const markdownTaskSaving = ref(false);
  let loadVersion = 0;

  async function loadData(force = false): Promise<void> {
    loadVersion += 1;
    loading.value = true;
    error.value = null;
    try {
      const response = await dashboardApi.getWidgetData(widgetId(), force, record());
      payload.value = response.payload;
      error.value = response.error ?? null;
    } catch (e) {
      // The server's reason, such as a ?record= the page does not accept.
      error.value = getErrorDetail(e, "Failed to load widget");
    } finally {
      loading.value = false;
    }
  }

  async function runHtmlAction(nodeId: string, event: WidgetActionEvent): Promise<void> {
    const version = loadVersion;
    const id = widgetId();
    const page = record();
    try {
      const response = await dashboardApi.runHtmlWidgetAction(id, nodeId, event, page);
      if (response.error) throw new Error(response.error);
      if (response.payload?.type === "html" && version === loadVersion &&
          id === widgetId() && page === record()) {
        payload.value = response.payload;
      }
    } catch (cause) {
      throw new Error(getErrorDetail(cause, cause instanceof Error ? cause.message : "Widget action failed"));
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
    runHtmlAction,
    toggleMarkdownTask,
    updateMarkdownTask,
  };
}
