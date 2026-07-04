<script setup lang="ts">
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, updateNodeData } = usePropertiesPanelContext();
</script>

<template>
  <div
    v-if="selectedNode"
    class="mt-4 border-t border-border pt-3"
  >
    <div class="flex items-center gap-2">
      <input
        id="node-highlight-output"
        type="checkbox"
        class="h-4 w-4 rounded border-input bg-background"
        :checked="!!selectedNode.data.highlight"
        @change="updateNodeData('highlight', ($event.target as HTMLInputElement).checked)"
      >
      <Label
        for="node-highlight-output"
        class="text-sm font-normal"
      >
        Highlight Node Output
      </Label>
    </div>
    <p class="mt-1 pl-6 text-xs text-muted-foreground">
      Show this node's output in the Canvas Execution Highlights popup.
    </p>
  </div>
</template>
