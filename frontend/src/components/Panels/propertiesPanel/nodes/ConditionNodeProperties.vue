<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  conditionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Condition</Label>
      <ExpressionInput
        ref="conditionInputRef"
        :model-value="selectedNode.data.condition || ''"
        :placeholder="`${exampleRef}.length > 0`"
        :rows="3"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Condition"
        field-key="condition"
        @update:model-value="updateNodeData('condition', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Use $ prefix: {{ exampleRef }}, $nodeName.field
      </p>
    </div>
  </template>
</template>
