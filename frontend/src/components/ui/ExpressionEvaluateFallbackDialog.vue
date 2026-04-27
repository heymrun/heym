<script setup lang="ts">
import { computed, onUnmounted, ref, watch, type Component } from "vue";
import { storeToRefs } from "pinia";
import { ChevronLeft, ChevronRight, Loader2, Play, Type, X } from "lucide-vue-next";

import type { WorkflowNode } from "@/types/workflow";
import ExpressionOutputPathPicker from "@/components/ui/ExpressionOutputPathPicker.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import {
  incomingEvaluateGraphNeighborNodes,
  outgoingEvaluateGraphNeighborNodes,
} from "@/lib/expressionEvaluateGraphNeighbors";
import { getLatestNodeResultForNode } from "@/lib/executionLog";
import { loopListSizeForEvaluateTitle } from "@/lib/loopNodeDisplay";
import { cn } from "@/lib/utils";
import { nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

const workflowStore = useWorkflowStore();
const { expressionEvaluateFallbackOpen, expressionEvaluateFallbackNodeId } = storeToRefs(workflowStore);

const fallbackNode = computed((): WorkflowNode | null => {
  const id = expressionEvaluateFallbackNodeId.value;
  if (!id) {
    return null;
  }
  return workflowStore.nodes.find((n) => n.id === id) ?? null;
});

const incomingNeighbors = computed((): WorkflowNode[] => {
  const nid = expressionEvaluateFallbackNodeId.value;
  const nodes = workflowStore.nodes;
  const edges = workflowStore.edges;
  if (!nid || !edges.length || !nodes.length) {
    return [];
  }
  return incomingEvaluateGraphNeighborNodes(nid, edges, nodes);
});

const outgoingNeighbors = computed((): WorkflowNode[] => {
  const nid = expressionEvaluateFallbackNodeId.value;
  const nodes = workflowStore.nodes;
  const edges = workflowStore.edges;
  if (!nid || !edges.length || !nodes.length) {
    return [];
  }
  return outgoingEvaluateGraphNeighborNodes(nid, edges, nodes);
});

const showGraphToolbar = computed((): boolean => {
  if (!expressionEvaluateFallbackOpen.value) {
    return false;
  }
  return incomingNeighbors.value.length > 0 || outgoingNeighbors.value.length > 0;
});

function nodeIcon(node: WorkflowNode): Component {
  return nodeIcons[node.type] ?? Type;
}

function nodeTint(node: WorkflowNode): string {
  return nodeIconColorClass[node.type] ?? "text-muted-foreground";
}

function truncateString(text: string, maxLen: number): string {
  if (text.length <= maxLen) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLen - 3))}...`;
}

const dialogHeading = computed((): string => {
  const n = fallbackNode.value;
  if (!n) {
    return "Evaluate";
  }
  const raw = n.data.label;
  const label = typeof raw === "string" ? raw.trim() : "";
  const name = label.length > 0 ? label : n.type;
  let base = `${name} – No expression fields`;
  const listSize = loopListSizeForEvaluateTitle(
    n.id,
    workflowStore.nodes,
    workflowStore.edges,
    workflowStore.nodeResults,
  );
  if (listSize !== null) {
    const suffix = listSize === 1 ? "1 item" : `${listSize} items`;
    base = `${base} (${suffix})`;
  }
  return base;
});

function resultForNode(nodeId: string): unknown {
  const row = getLatestNodeResultForNode(workflowStore.nodeResults, nodeId);
  return row?.output ?? null;
}

const thisNodeOutput = computed((): unknown => {
  const id = expressionEvaluateFallbackNodeId.value;
  if (!id) {
    return null;
  }
  return resultForNode(id);
});

const runLoading = ref(false);
const runRequestError = ref<string | null>(null);

function closeDialog(): void {
  workflowStore.closeExpressionEvaluateFallbackDialog();
}

const unsubDismiss = onDismissOverlays(() => {
  if (expressionEvaluateFallbackOpen.value) {
    closeDialog();
  }
});

onUnmounted(() => {
  unsubDismiss();
});

watch(expressionEvaluateFallbackOpen, (open): void => {
  if (open) {
    pushOverlayState();
    runRequestError.value = null;
  }
});

async function runWorkflow(): Promise<void> {
  const workflowId = workflowStore.currentWorkflow?.id;
  if (!workflowId || runLoading.value || workflowStore.isExecuting) {
    return;
  }
  runLoading.value = true;
  runRequestError.value = null;
  try {
    const executionResult = await workflowApi.execute(
      workflowId,
      workflowStore.buildExecutionRequestBody(),
      {
        bodyMode: workflowStore.currentWorkflow?.webhook_body_mode,
        testRun: true,
        triggerSource: "Canvas",
        simpleResponse: false,
      },
    );
    workflowStore.applyExecutionResultSnapshot(executionResult, { preserveSelection: true });
  } catch (e: unknown) {
    runRequestError.value = e instanceof Error ? e.message : String(e);
  } finally {
    runLoading.value = false;
  }
}

function handleNavigateToNode(targetNodeId: string): void {
  workflowStore.runExpressionGraphNavigate({ targetNodeId });
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="expressionEvaluateFallbackOpen"
      class="pointer-events-none fixed inset-0 z-[10000] flex items-center justify-center"
    >
      <div
        class="pointer-events-auto fixed inset-0 bg-black/50 backdrop-blur-sm"
        @click="closeDialog"
      />

      <div
        class="pointer-events-auto relative z-10 mx-4 flex max-h-[min(92vh,900px)] w-[min(96vw,1400px)] flex-col overflow-hidden rounded-lg border bg-background shadow-2xl"
        @click.stop
      >
        <div
          class="flex min-w-0 shrink-0 items-center justify-between border-b bg-background px-4 py-3"
        >
          <h3 class="min-w-0 flex-1 truncate pr-2 text-lg font-semibold">
            {{ dialogHeading }}
          </h3>
          <button
            type="button"
            class="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            @click="closeDialog"
          >
            <X class="h-5 w-5" />
          </button>
        </div>

        <div
          v-if="showGraphToolbar"
          class="grid w-full shrink-0 gap-3 border-b border-border/40 bg-background px-6 py-3 md:grid-cols-2"
        >
          <div
            v-if="incomingNeighbors.length > 0"
            class="min-w-0"
          >
            <div class="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Upstream
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="node in incomingNeighbors"
                :key="`incoming-${node.id}`"
                type="button"
                class="flex min-w-0 items-center gap-2 rounded-lg px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
                @click.stop="handleNavigateToNode(node.id)"
              >
                <ChevronLeft class="h-4 w-4 shrink-0 opacity-80" />
                <component
                  :is="nodeIcon(node)"
                  :class="cn('h-5 w-5 shrink-0', nodeTint(node))"
                />
                <span class="min-w-0 max-w-[min(72ch,min(960px,45vw))] truncate text-sm font-medium text-foreground">
                  {{ truncateString(node.data.label || node.type, 120) }}
                </span>
              </button>
            </div>
          </div>
          <div
            v-if="outgoingNeighbors.length > 0"
            :class="
              cn(
                'min-w-0 md:text-right',
                incomingNeighbors.length === 0 && 'w-full md:col-start-2',
              )
            "
          >
            <div
              :class="
                cn(
                  'mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground',
                  incomingNeighbors.length === 0 && 'text-right',
                )
              "
            >
              Downstream
            </div>
            <div
              :class="
                cn(
                  'flex flex-wrap gap-2',
                  incomingNeighbors.length === 0 ? 'justify-end' : 'md:justify-end',
                )
              "
            >
              <button
                v-for="node in outgoingNeighbors"
                :key="`outgoing-${node.id}`"
                type="button"
                class="flex min-w-0 items-center gap-2 rounded-lg px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
                @click.stop="handleNavigateToNode(node.id)"
              >
                <span class="min-w-0 max-w-[min(72ch,min(960px,45vw))] truncate text-sm font-medium text-foreground">
                  {{ truncateString(node.data.label || node.type, 120) }}
                </span>
                <component
                  :is="nodeIcon(node)"
                  :class="cn('h-5 w-5 shrink-0', nodeTint(node))"
                />
                <ChevronRight class="h-4 w-4 shrink-0 opacity-80" />
              </button>
            </div>
          </div>
        </div>

        <div
          class="min-h-0 max-h-[min(72vh,640px)] overflow-y-auto overflow-x-hidden overscroll-y-contain px-4 py-3"
        >
          <p class="mb-3 rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
            This node has no expression editor. You can still run a test execution to refresh results. Use the
            Properties panel to configure the node.
          </p>

          <div
            v-if="runRequestError"
            class="mb-3 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive"
          >
            {{ runRequestError }}
          </div>

          <div class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Upstream (last run)
          </div>
          <div
            v-if="incomingNeighbors.length === 0"
            class="mb-3 text-xs italic text-muted-foreground"
          >
            No incoming edges.
          </div>
          <div
            v-else
            class="mb-3 space-y-3"
          >
            <div
              v-for="src in incomingNeighbors"
              :key="src.id"
              class="min-w-0 rounded-md border border-border/60 bg-muted/15 px-3 py-2"
            >
              <div class="mb-2 text-xs font-medium text-foreground">
                {{ src.data.label || src.type }}
              </div>
              <div
                v-if="resultForNode(src.id) != null"
                class="max-h-[min(36vh,320px)] min-h-0 overflow-y-auto overflow-x-hidden overscroll-y-contain [scrollbar-gutter:stable]"
              >
                <ExpressionOutputPathPicker
                  :value="resultForNode(src.id)"
                  :default-collapsed="true"
                />
              </div>
              <p
                v-else
                class="text-xs italic text-muted-foreground"
              >
                No result yet — run the workflow.
              </p>
            </div>
          </div>

          <div
            class="mb-2 flex min-w-0 items-center justify-between gap-3"
          >
            <span class="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              This node (last run)
            </span>
            <button
              type="button"
              :disabled="!workflowStore.currentWorkflow?.id || runLoading || workflowStore.isExecuting"
              class="inline-flex shrink-0 items-center gap-2 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
              @click="runWorkflow"
            >
              <Loader2
                v-if="runLoading"
                class="h-3.5 w-3.5 animate-spin"
              />
              <Play
                v-else
                class="h-3.5 w-3.5 fill-current"
              />
              <span>Run test execution</span>
            </button>
          </div>
          <div class="min-w-0 rounded-md border border-border/60 bg-muted/15 px-3 py-2">
            <div
              v-if="thisNodeOutput != null"
              :key="String(expressionEvaluateFallbackNodeId)"
              class="max-h-[min(42vh,400px)] min-h-0 overflow-y-auto overflow-x-hidden overscroll-y-contain [scrollbar-gutter:stable]"
            >
              <ExpressionOutputPathPicker
                :value="thisNodeOutput"
                :default-collapsed="false"
              />
            </div>
            <p
              v-else
              class="text-xs italic text-muted-foreground"
            >
              No result yet — run the workflow.
            </p>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
