<script setup lang="ts">
import { computed } from "vue";
import { nodeIcons } from "@/lib/nodeIcons";
import type { NodeType } from "@/types/workflow";

interface Props {
  nodeType: string;
  label?: string;
}

const props = defineProps<Props>();

const icon = computed(() => {
  const type = props.nodeType as NodeType;
  return nodeIcons[type] ?? null;
});

const displayLabel = computed(() => {
  if (props.label) return props.label;
  return props.nodeType.charAt(0).toUpperCase() + props.nodeType.slice(1);
});
</script>

<template>
  <span
    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-muted/70 text-muted-foreground border border-border/40 shrink-0"
  >
    <component
      :is="icon"
      v-if="icon"
      class="w-3 h-3"
    />
    <span>{{ displayLabel }}</span>
  </span>
</template>
