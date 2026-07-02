<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  switchExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  updateNodeData,
  handleCasesChange,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Expression</Label>
      <ExpressionInput
        ref="switchExpressionInputRef"
        :model-value="selectedNode.data.expression || ''"
        :placeholder="exampleRef"
        :rows="3"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Expression"
        field-key="expression"
        @update:model-value="updateNodeData('expression', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Use $ prefix: {{ exampleRef }}, $nodeName.field
      </p>
    </div>
    <div class="space-y-2">
      <Label>Cases</Label>
      <Textarea
        :model-value="(selectedNode.data.cases || []).join('\n')"
        placeholder="case1&#10;case2"
        :rows="4"
        class="font-mono text-sm"
        @update:model-value="handleCasesChange($event)"
      />
      <p class="text-xs text-muted-foreground">
        One case per line, matched by value
      </p>
    </div>
  </template>
</template>
