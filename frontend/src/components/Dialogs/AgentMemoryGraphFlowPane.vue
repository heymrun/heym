<script setup lang="ts">
import { ref } from "vue";
import { Background } from "@vue-flow/background";
import { VueFlow } from "@vue-flow/core";
import type { Edge, Node } from "@vue-flow/core";

import AgentMemoryGraphEdge from "@/components/Dialogs/AgentMemoryGraphEdge.vue";
import AgentMemoryGraphFlowHotkeys from "./AgentMemoryGraphFlowHotkeys.vue";
import AgentMemoryFlowViewportFitter from "./AgentMemoryFlowViewportFitter.vue";

withDefaults(
  defineProps<{
    flowId: string;
    nodes: Node[];
    edges: Edge[];
    hotkeysEnabled?: boolean;
  }>(),
  { hotkeysEnabled: true },
);

const emit = defineEmits<{
  nodeClick: [payload: { node: Node }];
  paneClick: [];
  deleteSelection: [payload: { nodeIds: string[]; edgeIds: string[] }];
}>();

const fitterRef = ref<InstanceType<typeof AgentMemoryFlowViewportFitter> | null>(null);

async function fitViewAfterLoad(opts?: { padding?: number; duration?: number }): Promise<void> {
  await fitterRef.value?.fitViewAfterLoad(opts);
}

defineExpose({ fitViewAfterLoad });
</script>

<template>
  <VueFlow
    :id="flowId"
    class="agent-memory-vue-flow flex-1 min-h-[200px] lg:min-h-0 w-full h-full bg-background"
    :nodes="nodes"
    :edges="edges"
    :delete-key-code="null"
    :fit-view-on-init="true"
    :min-zoom="0.2"
    :max-zoom="1.5"
    @node-click="emit('nodeClick', $event)"
    @pane-click="emit('paneClick')"
  >
    <AgentMemoryFlowViewportFitter ref="fitterRef" />
    <AgentMemoryGraphFlowHotkeys
      :enabled="hotkeysEnabled"
      @delete-selection="emit('deleteSelection', $event)"
    />
    <template #node-default="slotProps">
      <slot
        name="node-default"
        v-bind="slotProps"
      />
    </template>
    <template #edge-agentMemory="edgeSlotProps">
      <AgentMemoryGraphEdge v-bind="edgeSlotProps" />
    </template>
    <Background pattern-color="hsl(var(--muted-foreground) / 0.18)" />
  </VueFlow>
</template>
