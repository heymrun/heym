<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Message</Label>
      <ExpressionInput
        :model-value="selectedNode.data.message || ''"
        placeholder="$error.message"
        :rows="3"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Message"
        field-key="message"
        @update:model-value="updateNodeData('message', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Use $error.message, $error.node_id, $error.node_label.
      </p>
    </div>
  </template>
</template>
