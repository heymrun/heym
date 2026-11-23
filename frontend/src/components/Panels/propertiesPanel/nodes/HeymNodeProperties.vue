<script setup lang="ts">
import { computed } from "vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import {
  getHeymBoardOperation,
  HEYM_CHAT_FIELD_KEYS,
  heymBoardOperations,
  isHeymChatOperation,
  type HeymBoardFieldKey,
} from "@/lib/heymOperations";
import { heymWorkflowIdForOperation, heymWorkflowPickerOptions } from "../heymWorkflowPicker";
import { heymOperationOptions } from "../operationOptions";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";
import HeymBoardPicker from "./HeymBoardPicker.vue";
import HeymChatFields from "./HeymChatFields.vue";

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
const boardField = computed(() => getHeymBoardOperation(operation.value)?.field);
const isChat = computed((): boolean => isHeymChatOperation(operation.value));
const needsWorkflow = computed(
  (): boolean => !boardField.value && !isChat.value && operation.value !== "listWorkflows",
);
const isHistory = computed((): boolean => operation.value === "getExecutionHistory");
const hasLimit = computed((): boolean => operation.value === "listWorkflows" || isHistory.value);
const workflowPickerOptions = computed(() =>
  heymWorkflowPickerOptions(operation.value, heymWorkflowOptions.value),
);

function onOperationChange(value: string | undefined): void {
  updateNodeData("heymOperation", value);
  const boardKey = getHeymBoardOperation(value)?.field.key;
  const supplied = selectedNode.value?.data.agentProvidedFields ?? [];
  const chatKeys = isHeymChatOperation(value) ? [] : HEYM_CHAT_FIELD_KEYS;
  const nextSupplied = supplied.filter((key) =>
    (key === boardKey || !heymBoardOperations.some(({ field }) => field.key === key))
    && !chatKeys.includes(key),
  );
  if (nextSupplied.length !== supplied.length) updateNodeData("agentProvidedFields", nextSupplied);
  if (boardKey) return;

  const current = selectedNode.value?.data.heymWorkflowId || "";
  const next = heymWorkflowIdForOperation(value ?? "", current);
  if (next !== current) updateNodeData("heymWorkflowId", next);
}

function selectBoardTarget(key: HeymBoardFieldKey, id: string): void {
  const node = selectedNode.value;
  if (!node) return;
  const supplied = node.data.agentProvidedFields ?? [];
  if (supplied.includes(key)) {
    workflowStore.updateNode(node.id, {
      [key]: id,
      agentProvidedFields: supplied.filter((field) => field !== key),
    });
  } else {
    updateNodeData(key, id);
  }
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Operation</Label>
      <Select
        data-testid="heym-operation"
        :model-value="operation"
        :options="heymOperationOptions"
        @update:model-value="onOperationChange"
      />
      <p
        v-if="isChat"
        class="text-xs text-muted-foreground"
      >
        Sends the message to Heym Chat as the user running the workflow.
      </p>
      <p
        v-else-if="boardField"
        class="text-xs text-muted-foreground"
      >
        Board access follows the user running the workflow.
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Reads are scoped to this workflow's owner: their own workflows plus anything shared
        with them.
      </p>
    </div>

    <HeymChatFields v-if="isChat" />

    <HeymBoardPicker
      v-if="boardField"
      :key="selectedNode.id"
      :field-key="boardField.key"
      :model-value="selectedNode.data[boardField.key] || ''"
      @select="selectBoardTarget(boardField.key, $event)"
    />

    <div
      v-for="field in boardField ? [boardField] : []"
      :key="field.key"
      :data-testid="`heym-field-${field.key}`"
      class="space-y-2"
    >
      <Label>{{ field.label }}</Label>
      <ExpressionInput
        :ref="(el: unknown) => setHeymExpressionInputRef(field.key, el)"
        :model-value="selectedNode.data[field.key] || ''"
        :placeholder="field.placeholder"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        :dialog-key-label="field.label"
        :field-key="field.key"
        @update:model-value="updateNodeData(field.key, $event)"
      />
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
