<script setup lang="ts">
import { AlertTriangle, ExternalLink } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  workflowOptions,
  executeTemplateExpressionInputRef,
  targetWorkflowInputFields,
  loadingTargetInputs,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  onExecuteMappingRegisterFieldIndex,
  getExpressionWarning,
  updateNodeData,
  executeMappings,
  handleExecuteMappingNavigate,
  setExecuteMappingInputRef,
  canVisitWorkflow,
  visitWorkflow,
  updateExecuteMapping,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Target Workflow</Label>
      <Select
        :model-value="selectedNode.data.executeWorkflowId || ''"
        :options="[{ value: '', label: 'Select a workflow...' }, ...workflowOptions]"
        @update:model-value="updateNodeData('executeWorkflowId', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Select which workflow to execute
      </p>
    </div>
    <Button
      v-if="canVisitWorkflow"
      variant="outline"
      size="sm"
      class="w-full gap-2"
      @click="visitWorkflow"
    >
      <ExternalLink class="w-4 h-4" />
      Visit Workflow
      <span class="text-xs text-muted-foreground ml-auto">⌘⇧O</span>
    </Button>

    <div
      v-if="loadingTargetInputs"
      class="flex items-center gap-2 text-sm text-muted-foreground py-2"
    >
      <div class="animate-spin w-4 h-4 border-2 border-primary border-t-transparent rounded-full" />
      Loading workflow inputs...
    </div>

    <div
      v-else-if="targetWorkflowInputFields.length > 0"
      class="space-y-3"
    >
      <div class="flex items-center justify-between">
        <Label>Input Mappings</Label>
        <span class="text-xs text-muted-foreground">
          {{ targetWorkflowInputFields.length }} field{{ targetWorkflowInputFields.length > 1 ? 's' : '' }}
        </span>
      </div>
      <div class="space-y-2 border rounded-md p-3 bg-muted/30">
        <div
          v-for="(mapping, index) in (selectedNode.data.executeInputMappings || [])"
          :key="mapping.key"
          class="space-y-1.5"
        >
          <div class="flex items-center gap-2">
            <span class="text-xs font-medium text-foreground bg-muted px-2 py-0.5 rounded">
              {{ mapping.key }}
            </span>
            <span
              v-if="targetWorkflowInputFields[index]?.defaultValue"
              class="text-xs text-muted-foreground"
            >
              (default: {{ targetWorkflowInputFields[index].defaultValue }})
            </span>
          </div>
          <ExpressionInput
            :ref="(el: any) => setExecuteMappingInputRef(index, el)"
            :model-value="mapping.value"
            :placeholder="`$input.${mapping.key}`"
            :rows="1"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            navigation-enabled
            :navigation-index="index"
            :navigation-total="executeMappings.length"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            :dialog-key-label="mapping.key"
            @update:model-value="updateExecuteMapping(index, $event)"
            @navigate="handleExecuteMappingNavigate"
            @register-field-index="onExecuteMappingRegisterFieldIndex"
          />
          <p
            v-if="getExpressionWarning(mapping.value)"
            class="text-xs text-amber-500 flex items-center gap-1 mt-1"
          >
            <AlertTriangle class="h-3 w-3" />
            {{ getExpressionWarning(mapping.value) }}
          </p>
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        Map values to the target workflow's input fields. Use $ expressions.
      </p>
    </div>

    <div
      v-else-if="selectedNode.data.executeWorkflowId"
      class="text-xs text-muted-foreground py-2"
    >
      Target workflow has no input fields defined.
    </div>

    <div
      v-if="!selectedNode.data.executeWorkflowId"
      class="space-y-2"
    >
      <Label>Input Template</Label>
      <ExpressionInput
        ref="executeTemplateExpressionInputRef"
        :model-value="selectedNode.data.executeInput || ''"
        :placeholder="exampleRef"
        :rows="3"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Input template"
        field-key="executeInput"
        @update:model-value="updateNodeData('executeInput', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Transform the input before passing downstream. Use $ prefix: {{ exampleRef }}
      </p>
    </div>
    <div class="flex items-center gap-2 pt-1">
      <input
        id="execute-do-not-wait"
        type="checkbox"
        class="h-4 w-4 rounded border-input bg-background"
        :checked="!!selectedNode.data.executeDoNotWait"
        @change="updateNodeData('executeDoNotWait', ($event.target as HTMLInputElement).checked)"
      >
      <Label
        for="execute-do-not-wait"
        class="text-sm font-normal"
      >
        Do not wait
      </Label>
    </div>
  </template>
</template>
