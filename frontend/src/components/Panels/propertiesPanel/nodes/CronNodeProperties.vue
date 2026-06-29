<script setup lang="ts">
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  selectedNode,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Cron Expression</Label>
      <Input
        :model-value="selectedNode.data.cronExpression || ''"
        placeholder="0 * * * *"
        @update:model-value="updateNodeData('cronExpression', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Use standard cron format to define the schedule.
      </p>
    </div>
  </template>
</template>
