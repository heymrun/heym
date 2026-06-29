<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const {
  labelError,
  selectedNode,
  reservedLabelError,
  handleLabelChange,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Label</Label>
      <Input
        :model-value="selectedNode.data.label"
        placeholder="camelCaseOnly"
        :class="{ 'border-red-500 focus:ring-red-500': reservedLabelError }"
        @update:model-value="handleLabelChange($event)"
      />
      <p
        v-if="reservedLabelError"
        class="text-xs text-red-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        {{ reservedLabelError }}
      </p>
      <p
        v-else-if="labelError"
        class="text-xs text-red-500"
      >
        {{ labelError }}
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        camelCase only (no spaces/special chars)
      </p>
    </div>
  </template>
</template>
