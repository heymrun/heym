<script setup lang="ts">
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  selectedNode,
  availableTargetNodes,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Target Node</Label>
      <Select
        :model-value="selectedNode.data.targetNodeLabel || ''"
        :options="availableTargetNodes"
        placeholder="Select node to disable"
        @update:model-value="updateNodeData('targetNodeLabel', $event)"
      />
      <p class="text-xs text-muted-foreground">
        The selected node will be permanently disabled when this node executes
      </p>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <div class="text-xs font-mono space-y-1 text-muted-foreground">
        <div>${{ selectedNode.data.label }}.targetNode - Disabled node label</div>
        <div>${{ selectedNode.data.label }}.disabled - Always true on success</div>
      </div>
    </div>
  </template>
</template>
