<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { VueFlow } from "@vue-flow/core";
import { MiniMap } from "@vue-flow/minimap";

import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";
import BaseNode from "@/components/Nodes/BaseNode.vue";
import InsertableEdge from "@/components/Canvas/InsertableEdge.vue";
import ReadonlyCanvasViewportFitter from "@/components/Canvas/ReadonlyCanvasViewportFitter.vue";
import StickyNoteNode from "@/components/Nodes/StickyNoteNode.vue";
import { buildSubAgentEdges, getSubAgentLabels } from "@/lib/agentCanvasLinks";

import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "@vue-flow/controls/dist/style.css";
import "@vue-flow/minimap/dist/style.css";

interface Props {
  nodes: WorkflowNode[];
  edges?: WorkflowEdge[];
  flowKey?: number | string;
  emptyMessage?: string;
  selectedNodeId?: string | null;
  interactive?: boolean;
  showControls?: boolean;
  showMiniMap?: boolean;
  fitPadding?: number;
  maxZoom?: number;
  backgroundGap?: number;
  framed?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  edges: () => [],
  flowKey: 0,
  emptyMessage: "No nodes to preview",
  selectedNodeId: null,
  interactive: true,
  showControls: true,
  showMiniMap: true,
  fitPadding: 0.22,
  maxZoom: 1.5,
  backgroundGap: 20,
  framed: true,
});

const emit = defineEmits<{
  (e: "node-click", value: { id: string; data: Record<string, unknown> }): void;
  (e: "pane-click"): void;
}>();

const containerRef = ref<HTMLDivElement | null>(null);
const containerWidth = ref(0);
const containerHeight = ref(0);
let resizeObserver: ResizeObserver | null = null;

const fitViewOptions = computed(() => ({
  padding: props.fitPadding,
  maxZoom: props.maxZoom,
}));
const hasContainerSize = computed((): boolean => containerWidth.value > 0 && containerHeight.value > 0);
const surfaceKey = computed((): string => `${props.flowKey}-${containerWidth.value}-${containerHeight.value}`);
const subAgentLabels = computed(() => getSubAgentLabels(props.nodes));
const vueFlowNodes = computed(() =>
  props.nodes.map((node) => {
    const isSubAgent =
      node.type === "agent" &&
      node.data.label &&
      subAgentLabels.value.has(node.data.label);

    return {
      id: node.id,
      type: "custom",
      position: node.position,
      data: {
        ...node.data,
        isSubAgent: !!isSubAgent,
        nodeId: node.id,
        nodeType: node.type,
      },
    };
  }),
);
const vueFlowEdges = computed(() =>
  [...props.edges, ...buildSubAgentEdges(props.nodes)].map((edge) => ({
    id: edge.id,
    type: "insertable",
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
    animated: true,
  })),
);

function handleNodeClick(event: { node: { id: string; data: Record<string, unknown> } }): void {
  if (!props.interactive) return;
  emit("node-click", { id: event.node.id, data: event.node.data });
}

function handlePaneClick(): void {
  if (!props.interactive) return;
  emit("pane-click");
}

function updateContainerSize(): void {
  const element = containerRef.value;
  containerWidth.value = Math.round(element?.clientWidth ?? 0);
  containerHeight.value = Math.round(element?.clientHeight ?? 0);
}

onMounted(() => {
  updateContainerSize();
  resizeObserver = new ResizeObserver(() => {
    updateContainerSize();
  });
  if (containerRef.value) {
    resizeObserver.observe(containerRef.value);
  }
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
});
</script>

<template>
  <div
    ref="containerRef"
    :class="[
      'h-full w-full min-h-0 min-w-0 overflow-hidden',
      framed ? 'rounded-xl border border-border/40' : 'border-0 rounded-none',
    ]"
    style="background: hsl(224 34% 10%)"
  >
    <VueFlow
      v-if="vueFlowNodes.length > 0 && hasContainerSize"
      :key="surfaceKey"
      :nodes="vueFlowNodes"
      :edges="vueFlowEdges"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :elements-selectable="false"
      :pan-on-drag="interactive"
      :pan-on-scroll="false"
      :min-zoom="0.1"
      :max-zoom="maxZoom"
      :zoom-on-scroll="interactive"
      :zoom-on-pinch="interactive"
      :zoom-on-double-click="false"
      fit-view-on-init
      :fit-view-options="fitViewOptions"
      :class="interactive ? 'h-full w-full' : 'pointer-events-none h-full w-full'"
      @node-click="handleNodeClick"
      @pane-click="handlePaneClick"
    >
      <template #node-custom="{ id, data }">
        <StickyNoteNode
          v-if="data.nodeType === 'sticky'"
          :id="id"
          :data="data"
          :selected="selectedNodeId === id"
        />
        <BaseNode
          v-else
          :id="id"
          :type="data.nodeType"
          :data="data"
          :selected="selectedNodeId === id"
        />
      </template>
      <template #edge-insertable="edgeProps">
        <InsertableEdge v-bind="edgeProps" />
      </template>
      <ReadonlyCanvasViewportFitter
        :fit-key="surfaceKey"
        :padding="fitPadding"
      />
      <Background
        pattern-color="hsl(var(--muted-foreground) / 0.1)"
        :gap="backgroundGap"
      />
      <Controls
        v-if="showControls"
        :show-interactive="false"
      />
      <MiniMap v-if="showMiniMap" />
    </VueFlow>

    <div
      v-else-if="vueFlowNodes.length === 0"
      class="flex h-full items-center justify-center bg-muted/15 px-6 text-sm text-muted-foreground"
    >
      {{ emptyMessage }}
    </div>
  </div>
</template>
