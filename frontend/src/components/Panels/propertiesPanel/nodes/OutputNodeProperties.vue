<script setup lang="ts">
import { AlertTriangle, Minus, Plus } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  outputMessageInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  getExpressionWarning,
  updateNodeData,
  outputSchema,
  addOutputSchemaField,
  updateOutputSchemaField,
  removeOutputSchemaField,
  outputExpressionFieldCount,
  setOutputSchemaValueInputRef,
  handleOutputExpressionFieldNavigate,
  onOutputRegisterExpressionFieldIndex,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <div class="flex items-center gap-2">
        <input
          id="output-downstream"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="!!selectedNode.data.allowDownstream"
          @change="updateNodeData('allowDownstream', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="output-downstream"
          class="text-sm font-normal"
        >
          Run downstream after output
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        Enable this to allow nodes to run after the output finishes.
      </p>
    </div>

    <div
      v-if="outputSchema.length === 0"
      class="space-y-2"
    >
      <Label>Message Template (simple/string)</Label>
      <ExpressionInput
        ref="outputMessageInputRef"
        :model-value="selectedNode.data.message || ''"
        :placeholder="exampleRef"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Message template"
        :navigation-enabled="outputExpressionFieldCount > 1"
        :navigation-index="0"
        :navigation-total="outputExpressionFieldCount"
        field-key="message"
        @navigate="handleOutputExpressionFieldNavigate"
        @register-field-index="onOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('message', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Simple template. Use $ prefix: {{ exampleRef }}. When JSON schema rows exist, the template is not
        used; remove all schema rows to edit the message again.
      </p>
    </div>

    <div class="space-y-3 pt-2 border-t">
      <div class="flex items-center justify-between">
        <Label>JSON Schema (key=value)</Label>
        <Button
          variant="ghost"
          size="sm"
          class="h-11 min-h-[44px] md:h-7 px-2"
          @click="addOutputSchemaField"
        >
          <Plus class="w-3 h-3 mr-1" />
          Add
        </Button>
      </div>
      <div
        v-for="(field, index) in outputSchema"
        :key="index"
        class="space-y-1"
      >
        <div class="flex gap-1.5 items-center">
          <Input
            :model-value="field.key"
            placeholder="key"
            class="w-20 shrink-0 font-mono text-xs"
            @update:model-value="updateOutputSchemaField(index, 'key', $event)"
          />
          <span class="text-muted-foreground text-xs">=</span>
          <ExpressionInput
            :ref="(el: unknown) => setOutputSchemaValueInputRef(index, el)"
            :model-value="field.value"
            placeholder="$node.field"
            single-line
            class="flex-1 text-xs"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            :dialog-key-label="field.key ? `Output field: ${field.key}` : 'Output schema value'"
            :navigation-enabled="outputExpressionFieldCount > 1"
            :navigation-index="index"
            :navigation-total="outputExpressionFieldCount"
            @navigate="handleOutputExpressionFieldNavigate"
            @register-field-index="onOutputRegisterExpressionFieldIndex"
            @update:model-value="updateOutputSchemaField(index, 'value', $event)"
          />
          <Button
            variant="ghost"
            size="icon"
            class="h-10 w-7 text-destructive shrink-0"
            @click="removeOutputSchemaField(index)"
          >
            <Minus class="w-3 h-3" />
          </Button>
        </div>
        <p
          v-if="getExpressionWarning(field.value)"
          class="text-xs text-amber-500 flex items-center gap-1 ml-1"
        >
          <AlertTriangle class="h-3 w-3" />
          {{ getExpressionWarning(field.value) }}
        </p>
      </div>
      <p class="text-xs text-muted-foreground">
        Build custom JSON output. Values support $ expressions.
      </p>
    </div>
  </template>
</template>
