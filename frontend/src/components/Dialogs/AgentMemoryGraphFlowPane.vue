<script setup lang="ts">
import { computed, ref } from "vue";
import { Background } from "@vue-flow/background";
import { VueFlow } from "@vue-flow/core";
import type { Edge, Node } from "@vue-flow/core";

import AgentMemoryGraphEdge from "@/components/Dialogs/AgentMemoryGraphEdge.vue";
import AgentMemoryGraphForceSim from "./AgentMemoryGraphForceSim.vue";
import AgentMemoryGraphFlowHotkeys from "./AgentMemoryGraphFlowHotkeys.vue";
import AgentMemoryFlowViewportFitter from "./AgentMemoryFlowViewportFitter.vue";

const props = withDefaults(
  defineProps<{
    flowId: string;
    nodes: Node[];
    edges: Edge[];
    hotkeysEnabled?: boolean;
    selectedNodeId?: string | null;
  }>(),
  { hotkeysEnabled: true, selectedNodeId: null },
);

const emit = defineEmits<{
  nodeClick: [payload: { node: Node }];
  edgeClick: [payload: { edge: Edge }];
  edgeMouseEnter: [payload: { edge: Edge }];
  edgeMouseLeave: [payload: { edge: Edge }];
  paneClick: [];
  deleteSelection: [payload: { nodeIds: string[]; edgeIds: string[] }];
}>();

const fitterRef = ref<InstanceType<typeof AgentMemoryFlowViewportFitter> | null>(null);
const simRef = ref<InstanceType<typeof AgentMemoryGraphForceSim> | null>(null);

const simLinks = computed(() => props.edges.map((e) => ({ source: e.source, target: e.target })));

async function fitViewAfterLoad(opts?: { padding?: number; duration?: number }): Promise<void> {
  await fitterRef.value?.fitViewAfterLoad(opts);
}

async function focusNodes(ids: string[]): Promise<void> {
  await fitterRef.value?.focusOnNodes(ids);
}

function reheat(): void {
  simRef.value?.reheat();
}

function snapshotPositions(): Map<string, { x: number; y: number }> {
  return simRef.value?.snapshotPositions() ?? new Map();
}

function handleNodeDragStop(): void {
  simRef.value?.reheat();
}

defineExpose({ fitViewAfterLoad, focusNodes, reheat, snapshotPositions });
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
    @edge-click="emit('edgeClick', $event)"
    @edge-mouse-enter="emit('edgeMouseEnter', $event)"
    @edge-mouse-leave="emit('edgeMouseLeave', $event)"
    @pane-click="emit('paneClick')"
    @node-drag-stop="handleNodeDragStop"
  >
    <AgentMemoryFlowViewportFitter ref="fitterRef" />
    <AgentMemoryGraphForceSim
      ref="simRef"
      :links="simLinks"
      :active="nodes.length > 0"
      :focus-node-id="selectedNodeId"
    />
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
