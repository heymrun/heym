import { computed, nextTick, ref, watch, type ComputedRef, type Ref } from "vue";

import { useWorkflowStore } from "@/stores/workflow";

interface RunPanelTarget {
  runPanel: Ref<HTMLElement | null>;
  runLabel: ComputedRef<string>;
}

export function useRunPanelTarget(): RunPanelTarget {
  const workflowStore = useWorkflowStore();
  const runPanel = ref<HTMLElement | null>(null);
  const runLabel = computed(() => workflowStore.runUntilNode
    ? `Run to ${workflowStore.runUntilNode.data.label}` : "Run Workflow");
  watch(
    () => workflowStore.runInputFocusRequest,
    async (request) => {
      if (!request || !workflowStore.runUntilNodeId) return;
      await nextTick();
      runPanel.value?.querySelector<HTMLTextAreaElement>("textarea:not(:disabled)")?.focus();
    },
    { immediate: true, flush: "post" },
  );
  return { runPanel, runLabel };
}
