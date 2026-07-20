<script setup lang="ts">
import { onMounted } from "vue";

import DebugPanel from "@/components/Panels/DebugPanel.vue";
import { useWorkflowStore } from "@/stores/workflow";
import type { ExecutionResult, NodeResult } from "@/types/workflow";

const workflowStore = useWorkflowStore();

onMounted(() => {
  const nodeResults: NodeResult[] = [
    {
      node_id: "build_json",
      node_label: "Build JSON",
      node_type: "set",
      status: "success",
      execution_time_ms: 333,
      output: {
        message: "Hello from JSON viewer",
        count: 42,
        nested: { flag: true, items: ["a", "b", "c"] },
      },
      error: null,
    },
  ];

  const executionResult: ExecutionResult = {
    workflow_id: "workflow-screenshot",
    status: "success",
    outputs: {
      result: {
        message: "Hello from JSON viewer",
        count: 42,
        nested: { flag: true, items: ["a", "b", "c"] },
      },
    },
    execution_time_ms: 333,
    node_results: nodeResults,
  };

  workflowStore.nodeResults = nodeResults;
  workflowStore.executionResult = executionResult;
});
</script>

<template>
  <div class="h-screen w-screen flex flex-col bg-background">
    <div class="flex-1 min-h-0" />
    <DebugPanel />
  </div>
</template>
