<script setup lang="ts">
import { AlertTriangle, Plus, X } from "lucide-vue-next";
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  onSetMappingRegisterFieldIndex,
  getMappingKeyError,
  getExpressionWarning,
  mappings,
  addMappingField,
  updateMappingField,
  removeMappingField,
  handleSetMappingNavigate,
  setMappingInputRef,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-3">
      <div class="flex items-center justify-between">
        <Label>Mappings (key = value)</Label>
        <Button
          variant="ghost"
          size="sm"
          class="h-11 min-h-[44px] md:h-7 px-2"
          @click="addMappingField"
        >
          <Plus class="w-3 h-3 mr-1" />
          Add
        </Button>
      </div>
      <div
        v-for="(mapping, index) in mappings"
        :key="index"
        class="space-y-1"
      >
        <div class="grid grid-cols-[4rem_auto_minmax(0,1fr)_auto_auto] items-center gap-1.5">
          <Input
            :model-value="mapping.key"
            placeholder="key"
            :class="[
              'w-full font-mono text-xs',
              getMappingKeyError(mapping.key) ? 'border-red-500 focus:ring-red-500' : ''
            ]"
            @update:model-value="updateMappingField(index, 'key', $event)"
          />
          <span class="text-muted-foreground text-xs">=</span>
          <ExpressionInput
            :ref="(el: any) => setMappingInputRef(index, el)"
            :model-value="mapping.value"
            :placeholder="exampleRef"
            single-line
            class="flex-1 text-xs"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            navigation-enabled
            :navigation-index="index"
            :navigation-total="mappings.length"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            :dialog-key-label="mapping.key || `mapping ${index + 1}`"
            @update:model-value="updateMappingField(index, 'value', $event)"
            @navigate="handleSetMappingNavigate"
            @register-field-index="onSetMappingRegisterFieldIndex"
          />
          <button
            type="button"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-input bg-background text-muted-foreground shadow-sm transition-colors hover:bg-destructive/10 hover:text-destructive"
            title="Remove"
            @click="removeMappingField(index)"
          >
            <X class="w-3 h-3" />
          </button>
          <AgentFieldToggle
            :node-id="selectedNode.id"
            :field-key="mapping.key || `mapping_${index}`"
          />
        </div>
        <p
          v-if="getMappingKeyError(mapping.key)"
          class="text-xs text-red-500 flex items-center gap-1 ml-1"
        >
          <AlertTriangle class="h-3 w-3" />
          {{ getMappingKeyError(mapping.key) }}
        </p>
        <p
          v-if="getExpressionWarning(mapping.value)"
          class="text-xs text-amber-500 flex items-center gap-1 ml-1"
        >
          <AlertTriangle class="h-3 w-3" />
          {{ getExpressionWarning(mapping.value) }}
        </p>
      </div>
      <p
        v-if="selectedNode.type === 'set'"
        class="text-xs text-muted-foreground"
      >
        Transform input data to custom output. Values support $ expressions like {{ exampleRef }}
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Builds the JSON object returned to webhook and run callers when this node is the only terminal
        (no <code class="text-[10px]">result</code> wrapper or outer node label). Values support
        $ expressions like {{ exampleRef }}
      </p>
    </div>
  </template>
</template>
