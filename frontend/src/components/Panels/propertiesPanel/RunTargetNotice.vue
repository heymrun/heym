<script setup lang="ts">
import Button from "@/components/ui/Button.vue";
import { useWorkflowStore } from "@/stores/workflow";

const workflowStore = useWorkflowStore();
</script>

<template>
  <div
    v-if="workflowStore.runUntilNode"
    class="flex items-center justify-between gap-2 text-xs"
  >
    <span class="truncate">Run to <strong>{{ workflowStore.runUntilNode.data.label }}</strong></span>
    <Button
      variant="ghost"
      size="sm"
      class="shrink-0 px-2"
      :disabled="workflowStore.isExecuting"
      @click="workflowStore.runUntilNodeId = null"
    >
      Run full workflow
    </Button>
  </div>
</template>
