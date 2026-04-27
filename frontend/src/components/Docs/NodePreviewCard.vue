<script setup lang="ts">
import { computed } from "vue";

import { nodeIcons } from "@/lib/nodeIcons";
import { NODE_DEFINITIONS } from "@/types/node";
import type { NodeType } from "@/types/workflow";

const NODE_COLOR_MAP: Record<string, string> = {
  "node-input": "bg-node-input/15 border-node-input/40",
  "node-cron": "bg-node-cron/15 border-node-cron/40",
  "node-llm": "bg-node-llm/15 border-node-llm/40",
  "node-agent": "bg-node-agent/15 border-node-agent/40",
  "node-condition": "bg-node-condition/15 border-node-condition/40",
  "node-switch": "bg-node-switch/15 border-node-switch/40",
  "node-execute": "bg-node-execute/15 border-node-execute/40",
  "node-output": "bg-node-output/15 border-node-output/40",
  "node-wait": "bg-node-wait/15 border-node-wait/40",
  "node-http": "bg-node-http/15 border-node-http/40",
  "node-merge": "bg-node-merge/15 border-node-merge/40",
  "node-set": "bg-node-set/15 border-node-set/40",
  "node-variable": "bg-node-variable/15 border-node-variable/40",
  "node-loop": "bg-node-loop/20 border-node-loop/40",
  "node-rag": "bg-node-rag/15 border-node-rag/40",
};

interface Props {
  nodeType: NodeType;
}

const props = defineProps<Props>();

const definition = computed(() => NODE_DEFINITIONS[props.nodeType]);

const IconComponent = computed(() => {
  if (!definition.value) return null;
  return nodeIcons[props.nodeType] ?? null;
});

const colorClass = computed(() => {
  if (!definition.value) return "bg-muted/50 border-border";
  return NODE_COLOR_MAP[definition.value.color] ?? "bg-muted/50 border-border";
});
</script>

<template>
  <div
    v-if="definition"
    :class="[
      'inline-flex items-center gap-2 px-3 py-2 rounded-xl border text-sm font-medium',
      colorClass,
    ]"
  >
    <component
      :is="IconComponent"
      v-if="IconComponent"
      class="w-4 h-4 shrink-0"
    />
    <span>{{ definition.label }}</span>
    <span class="text-xs text-muted-foreground">
      {{ definition.inputsDisplay ?? definition.inputs }}→{{ definition.outputsDisplay ?? definition.outputs }}
    </span>
  </div>
</template>
