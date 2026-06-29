<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  loopArrayExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  getExpressionWarning,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Array Expression</Label>
      <ExpressionInput
        ref="loopArrayExpressionInputRef"
        :model-value="selectedNode.data.arrayExpression || ''"
        placeholder="$input.items"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Array expression"
        field-key="arrayExpression"
        @update:model-value="updateNodeData('arrayExpression', $event)"
      />
      <p
        v-if="getExpressionWarning(selectedNode.data.arrayExpression || '')"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        {{ getExpressionWarning(selectedNode.data.arrayExpression || '') }}
      </p>
      <p class="text-xs text-muted-foreground">
        Expression that resolves to an array to iterate over
      </p>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Outputs</Label>
      <div class="text-xs space-y-1">
        <div class="flex items-center gap-2">
          <span class="px-1.5 py-0.5 rounded bg-node-loop/20 text-node-loop font-medium">loop</span>
          <span class="text-muted-foreground">Runs for each item in array</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="px-1.5 py-0.5 rounded bg-green-500/20 text-green-500 font-medium">done</span>
          <span class="text-muted-foreground">Runs after all iterations complete</span>
        </div>
      </div>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Available Fields</Label>
      <div class="text-xs font-mono space-y-1 text-muted-foreground">
        <div>${{ selectedNode.data.label }}.item - Current item</div>
        <div>${{ selectedNode.data.label }}.index - Current index (0-based)</div>
        <div>${{ selectedNode.data.label }}.total - Total items count</div>
        <div>${{ selectedNode.data.label }}.isFirst - Boolean</div>
        <div>${{ selectedNode.data.label }}.isLast - Boolean</div>
      </div>
    </div>
  </template>
</template>
