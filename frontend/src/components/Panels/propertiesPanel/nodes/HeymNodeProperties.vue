<script setup lang="ts">
import { computed } from "vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import { heymWorkflowIdForOperation, heymWorkflowPickerOptions } from "../heymWorkflowPicker";
import { heymOperationOptions } from "../operationOptions";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  heymWorkflowOptions,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
  heymExpressionFieldCount,
  heymExpressionFieldIndex,
  setHeymExpressionInputRef,
  handleHeymExpressionFieldNavigate,
  onHeymRegisterExpressionFieldIndex,
} = usePropertiesPanelContext();

const operation = computed((): string => selectedNode.value?.data.heymOperation || "listWorkflows");
const needsWorkflow = computed((): boolean => operation.value !== "listWorkflows");
const isHistory = computed((): boolean => operation.value === "getExecutionHistory");
/** Only `getWorkflow` returns a single record, so it is the one operation without a limit. */
const hasLimit = computed((): boolean => operation.value !== "getWorkflow");
const workflowPickerOptions = computed(() =>
  heymWorkflowPickerOptions(operation.value, heymWorkflowOptions.value),
);

function onOperationChange(value: string | undefined): void {
  updateNodeData("heymOperation", value);
  const current = selectedNode.value?.data.heymWorkflowId || "";
  const next = heymWorkflowIdForOperation(value ?? "", current);
  if (next !== current) updateNodeData("heymWorkflowId", next);
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Operation</Label>
      <Select
        :model-value="operation"
        :options="heymOperationOptions"
        @update:model-value="onOperationChange"
      />
      <p class="text-xs text-muted-foreground">
        Reads are scoped to this workflow's owner: their own workflows plus anything shared
        with them.
      </p>
    </div>

    <div
      v-if="needsWorkflow"
      class="space-y-2"
    >
      <Label>Workflow</Label>
      <SearchableSelect
        :model-value="selectedNode.data.heymWorkflowId || ''"
        :options="workflowPickerOptions"
        placeholder="Select a workflow..."
        search-placeholder="Search workflows..."
        @update:model-value="updateNodeData('heymWorkflowId', $event)"
      />
    </div>

    <template v-if="isHistory">
      <div class="space-y-2">
        <Label>Status filter</Label>
        <ExpressionInput
          :ref="(el: unknown) => setHeymExpressionInputRef('heymStatus', el)"
          :model-value="selectedNode.data.heymStatus || ''"
          placeholder="success"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Status filter"
          field-key="heymStatus"
          :navigation-enabled="heymExpressionFieldCount > 1"
          :navigation-index="heymExpressionFieldIndex('heymStatus')"
          :navigation-total="heymExpressionFieldCount"
          @navigate="handleHeymExpressionFieldNavigate"
          @register-field-index="onHeymRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('heymStatus', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Leave empty to include every status.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Since (days)</Label>
        <ExpressionInput
          :ref="(el: unknown) => setHeymExpressionInputRef('heymSinceDays', el)"
          :model-value="selectedNode.data.heymSinceDays || ''"
          placeholder="7"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Since (days)"
          field-key="heymSinceDays"
          :navigation-enabled="heymExpressionFieldCount > 1"
          :navigation-index="heymExpressionFieldIndex('heymSinceDays')"
          :navigation-total="heymExpressionFieldCount"
          @navigate="handleHeymExpressionFieldNavigate"
          @register-field-index="onHeymRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('heymSinceDays', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Leave empty to cover the full history.
        </p>
      </div>
    </template>

    <div
      v-if="hasLimit"
      class="space-y-2"
    >
      <Label>Limit</Label>
      <ExpressionInput
        :ref="(el: unknown) => setHeymExpressionInputRef('heymLimit', el)"
        :model-value="selectedNode.data.heymLimit || ''"
        placeholder="0"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Limit"
        field-key="heymLimit"
        :navigation-enabled="heymExpressionFieldCount > 1"
        :navigation-index="heymExpressionFieldIndex('heymLimit')"
        :navigation-total="heymExpressionFieldCount"
        @navigate="handleHeymExpressionFieldNavigate"
        @register-field-index="onHeymRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('heymLimit', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Leave empty or enter <code>0</code> to return everything.
        <span v-if="isHistory">`total` and `by_status` always cover the full history, even when
          the returned entries are capped.</span>
        <span v-else>`total` always reports the full count, even when the returned rows are
          capped.</span>
      </p>
    </div>
  </template>
</template>
