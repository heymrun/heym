<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  variableValueInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  variableTypeOptions,
  variableNameError,
  getExpressionWarning,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Variable Name</Label>
      <Input
        :model-value="selectedNode.data.variableName || ''"
        placeholder="myVariable"
        :class="{ 'border-red-500 focus:ring-red-500': variableNameError }"
        @update:model-value="updateNodeData('variableName', $event)"
      />
      <p
        v-if="variableNameError"
        class="text-xs text-red-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        {{ variableNameError }}
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Access via: {{ selectedNode.data.isGlobal ? '$global' : '$vars' }}.{{ selectedNode.data.variableName ||
          'variableName' }}
      </p>
    </div>
    <div class="space-y-2">
      <Label>Value</Label>
      <ExpressionInput
        ref="variableValueInputRef"
        :model-value="selectedNode.data.variableValue || ''"
        :placeholder="`${exampleRef} or literal value`"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Value"
        field-key="variableValue"
        @update:model-value="updateNodeData('variableValue', $event)"
      />
      <p
        v-if="getExpressionWarning(selectedNode.data.variableValue || '')"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        {{ getExpressionWarning(selectedNode.data.variableValue || '') }}
      </p>
      <p class="text-xs text-muted-foreground">
        Use $ expressions or enter a literal value
      </p>
    </div>
    <div class="space-y-2">
      <Label>Type</Label>
      <Select
        :model-value="selectedNode.data.variableType || 'auto'"
        :options="variableTypeOptions"
        @update:model-value="updateNodeData('variableType', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Auto-detect or force a specific type
      </p>
    </div>
    <div class="flex items-center gap-2 pt-2">
      <input
        :id="`variable-isGlobal-${selectedNode.id}`"
        type="checkbox"
        :checked="!!selectedNode.data.isGlobal"
        class="rounded border-border"
        @change="updateNodeData('isGlobal', ($event.target as HTMLInputElement).checked)"
      >
      <Label
        :for="`variable-isGlobal-${selectedNode.id}`"
        class="cursor-pointer text-sm font-normal"
      >
        Store in Global Variable Store
      </Label>
    </div>
  </template>
</template>
