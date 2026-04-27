<script setup lang="ts">
import { computed } from "vue";
import { Check, ChevronDown, X } from "lucide-vue-next";

import type { NodeType, WorkflowEdge, WorkflowNode } from "@/types/workflow";
import type { ReadonlyPreviewDisplayField } from "@/components/Canvas/readonlyPreviewFields";
import ReadonlyCanvasSurface from "@/components/Canvas/ReadonlyCanvasSurface.vue";
import { getReadonlyPreviewFields } from "@/components/Canvas/readonlyPreviewFields";
import { nodeIcons } from "@/lib/nodeIcons";
import { NODE_DEFINITIONS } from "@/types/node";

interface Props {
  nodes: WorkflowNode[];
  edges?: WorkflowEdge[];
  selectedNode?: Record<string, unknown> | null;
  flowKey?: number | string;
  emptyMessage?: string;
}

interface PreviewNodeData extends Record<string, unknown> {
  nodeId: string;
  nodeType: NodeType;
  label?: string;
}

const props = withDefaults(defineProps<Props>(), {
  edges: () => [],
  selectedNode: null,
  flowKey: 0,
  emptyMessage: "No nodes to preview",
});

const emit = defineEmits<{
  (e: "update:selectedNode", value: Record<string, unknown> | null): void;
}>();

const activeNode = computed((): PreviewNodeData | null => props.selectedNode as PreviewNodeData | null);
const activeNodeType = computed((): NodeType | null => {
  const rawType = activeNode.value?.nodeType;
  return typeof rawType === "string" ? (rawType as NodeType) : null;
});
const activeNodeDefinition = computed(() => {
  if (!activeNodeType.value) return null;
  return NODE_DEFINITIONS[activeNodeType.value] ?? null;
});
const activeNodeIcon = computed(() => {
  if (!activeNodeType.value) return nodeIcons.llm;
  return nodeIcons[activeNodeType.value] ?? nodeIcons.llm;
});
const activeNodeColor = computed((): string => `hsl(var(--${activeNodeDefinition.value?.color ?? "node-llm"}))`);
const activeNodeTypeLabel = computed((): string => activeNodeDefinition.value?.label ?? String(activeNodeType.value ?? "Node"));
const activeNodeFields = computed((): ReadonlyPreviewDisplayField[] =>
  activeNode.value ? getReadonlyPreviewFields(activeNode.value) : [],
);
const fitPadding = computed((): number => (props.nodes.length <= 1 ? 0.9 : 0.22));

function handleNodeClick(event: { id: string; data: Record<string, unknown> }): void {
  emit("update:selectedNode", { ...event.data, nodeId: event.id });
}

function clearSelection(): void {
  emit("update:selectedNode", null);
}
</script>

<template>
  <div class="flex h-full flex-col gap-3 lg:flex-row">
    <ReadonlyCanvasSurface
      :flow-key="flowKey"
      :nodes="nodes"
      :edges="edges"
      :selected-node-id="activeNode?.nodeId ?? null"
      :fit-padding="fitPadding"
      :empty-message="emptyMessage"
      @node-click="handleNodeClick"
      @pane-click="clearSelection"
    />

    <Transition name="panel">
      <div
        v-if="activeNode"
        class="flex h-64 w-full shrink-0 flex-col overflow-hidden rounded-xl border border-border/50 bg-card shadow-sm lg:h-auto lg:w-72"
      >
        <div class="shrink-0 border-b border-border/40 px-4 py-3">
          <div class="flex items-start justify-between gap-2">
            <div class="flex min-w-0 items-center gap-2.5">
              <div
                class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
                :style="{ background: `hsl(var(--${activeNodeDefinition?.color ?? 'node-llm'}) / 0.15)` }"
              >
                <component
                  :is="activeNodeIcon"
                  class="h-4 w-4"
                  :style="{ color: activeNodeColor }"
                />
              </div>
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold leading-tight">
                  {{ String(activeNode.label || "Node") }}
                </p>
                <p
                  class="text-[11px] font-medium"
                  :style="{ color: activeNodeColor }"
                >
                  {{ activeNodeTypeLabel }}
                </p>
              </div>
            </div>
            <button
              class="mt-0.5 flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
              type="button"
              @click="clearSelection"
            >
              <X class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <div class="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
          <template v-if="activeNodeFields.length > 0">
            <div
              v-for="field in activeNodeFields"
              :key="field.key"
              class="space-y-1.5"
            >
              <label
                v-if="field.kind === 'boolean'"
                class="flex cursor-default select-none items-center gap-2.5"
              >
                <span
                  class="flex h-4 w-4 shrink-0 items-center justify-center rounded border"
                  :class="field.isTrue ? 'border-primary bg-primary' : 'border-border bg-background'"
                >
                  <Check
                    v-if="field.isTrue"
                    class="h-2.5 w-2.5 text-primary-foreground"
                  />
                </span>
                <span class="text-sm font-medium leading-tight text-foreground">{{ field.label }}</span>
              </label>

              <template v-else-if="field.kind === 'textarea'">
                <p class="text-xs font-medium text-muted-foreground">
                  {{ field.label }}
                </p>
                <div class="max-h-44 min-h-[72px] w-full overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-input bg-background/60 px-3 py-2 font-mono text-xs leading-relaxed text-foreground/90">
                  {{ field.value }}
                </div>
              </template>

              <template v-else-if="field.kind === 'select'">
                <p class="text-xs font-medium text-muted-foreground">
                  {{ field.label }}
                </p>
                <div class="relative">
                  <div class="w-full truncate rounded-lg border border-input bg-background/60 px-3 py-2 pr-8 text-sm text-foreground">
                    {{ field.value }}
                  </div>
                  <ChevronDown class="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                </div>
              </template>

              <template v-else>
                <p class="text-xs font-medium text-muted-foreground">
                  {{ field.label }}
                </p>
                <div class="w-full truncate rounded-lg border border-input bg-background/60 px-3 py-2 text-sm text-foreground">
                  {{ field.value }}
                </div>
              </template>
            </div>
          </template>

          <div
            v-else
            class="flex items-center justify-center py-8 text-xs text-muted-foreground"
          >
            No displayable fields
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.panel-enter-active,
.panel-leave-active {
  transition: all 0.18s ease;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
  transform: translateX(10px);
}
</style>
