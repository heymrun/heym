import { computed, type ComputedRef } from "vue";

import type { WorkflowConcurrencyPatch } from "@/types/workflow";
import { toConcurrencyUpdatePayload } from "@/components/Panels/propertiesPanel/concurrencySettings";
import { workflowApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import { useWorkflowStore } from "@/stores/workflow";

export interface WorkflowConcurrencySettingsState {
  limit: ComputedRef<number | null>;
  maxQueue: ComputedRef<number | null>;
  maxWaitSeconds: ComputedRef<number | null>;
  readOnly: ComputedRef<boolean>;
  save: (patch: WorkflowConcurrencyPatch) => Promise<void>;
}

/** The owner changes the limit; collaborators see it, and the server refuses their change. */
export function useWorkflowConcurrencySettings(): WorkflowConcurrencySettingsState {
  const workflowStore = useWorkflowStore();
  const authStore = useAuthStore();

  const limit = computed(() => workflowStore.currentWorkflow?.concurrency_limit ?? null);
  const maxQueue = computed(() => workflowStore.currentWorkflow?.concurrency_max_queue ?? null);
  const maxWaitSeconds = computed(
    () => workflowStore.currentWorkflow?.concurrency_max_wait_seconds ?? null,
  );
  const readOnly = computed(
    () =>
      workflowStore.isReadOnly ||
      !authStore.user ||
      workflowStore.currentWorkflow?.owner_id !== authStore.user.id,
  );

  async function save(patch: WorkflowConcurrencyPatch): Promise<void> {
    const wf = workflowStore.currentWorkflow;
    if (!wf || readOnly.value) return;
    const previous: WorkflowConcurrencyPatch = {
      concurrency_limit: wf.concurrency_limit ?? null,
      concurrency_max_queue: wf.concurrency_max_queue ?? null,
      concurrency_max_wait_seconds: wf.concurrency_max_wait_seconds ?? null,
    };
    Object.assign(wf, patch);
    try {
      await workflowApi.update(wf.id, toConcurrencyUpdatePayload(patch));
    } catch {
      Object.assign(wf, previous);
    }
  }

  return { limit, maxQueue, maxWaitSeconds, readOnly, save };
}
