<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  chartOutputExpressionFieldCount,
  chartOutputExpressionFieldIndex,
  setChartOutputExpressionInputRef,
  handleChartOutputExpressionFieldNavigate,
  onChartOutputRegisterExpressionFieldIndex,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Link column (optional)</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('linkColumn', el)"
        :model-value="selectedNode.data.linkColumn || ''"
        placeholder="column that holds a URL, e.g. url"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Link column"
        field-key="linkColumn"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('linkColumn')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('linkColumn', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Each cell in this column becomes a button that opens its URL in a new tab. Use a full
        https:// address for another site, or a path such as /dashboards for a page in Heym.
      </p>
    </div>

    <div class="space-y-2">
      <Label>Link button text (optional)</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('linkLabel', el)"
        :model-value="selectedNode.data.linkLabel || ''"
        placeholder="empty shows only the link icon"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Link button text"
        field-key="linkLabel"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('linkLabel')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('linkLabel', $event)"
      />
    </div>
  </template>
</template>
