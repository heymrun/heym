<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  consoleLogMessageInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Log message</Label>
      <ExpressionInput
        ref="consoleLogMessageInputRef"
        :model-value="selectedNode.data.logMessage || ''"
        :placeholder="exampleRef"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Log message"
        field-key="logMessage"
        @update:model-value="updateNodeData('logMessage', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Written to backend (server) console only; not visible in the browser.
      </p>
    </div>
  </template>
</template>
