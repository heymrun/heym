import { ref, watch } from "vue";
import type { Ref } from "vue";

import type { AllExecutionHistoryEntryLight, Workflow } from "@/types/workflow";
import { workflowApi } from "@/services/api";

export interface WorkflowPreviewApi {
  detail: Ref<Workflow | null>;
  lastRun: Ref<AllExecutionHistoryEntryLight | null>;
  loading: Ref<boolean>;
  error: Ref<string | null>;
  reload: () => Promise<void>;
}

/**
 * Loads the full workflow and its most recent run for the preview panel, keyed off the
 * current selection. Stale responses from a previous selection are discarded.
 */
export function useWorkflowPreview(selectedId: Ref<string | null>): WorkflowPreviewApi {
  const detail = ref<Workflow | null>(null);
  const lastRun = ref<AllExecutionHistoryEntryLight | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  let requestGeneration = 0;

  async function load(): Promise<void> {
    const id = selectedId.value;
    requestGeneration += 1;
    const generation = requestGeneration;

    if (!id) {
      detail.value = null;
      lastRun.value = null;
      loading.value = false;
      error.value = null;
      return;
    }

    loading.value = true;
    error.value = null;

    const [detailResult, historyResult] = await Promise.allSettled([
      workflowApi.get(id),
      workflowApi.getLatestRun(id),
    ]);

    if (generation !== requestGeneration) return;

    if (detailResult.status === "fulfilled") {
      detail.value = detailResult.value;
    } else {
      detail.value = null;
      error.value = "Could not load this workflow's details.";
    }

    lastRun.value = historyResult.status === "fulfilled" ? historyResult.value : null;

    loading.value = false;
  }

  watch(selectedId, () => void load(), { immediate: true });

  return { detail, lastRun, loading, error, reload: load };
}
