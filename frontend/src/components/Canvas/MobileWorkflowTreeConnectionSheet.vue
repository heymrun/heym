<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Check, GitBranch, Search, X } from "lucide-vue-next";

import { isTileFillingIcon, nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";
import { NODE_DEFINITIONS } from "@/types/node";
import type { WorkflowNode } from "@/types/workflow";
import type { MobileWorkflowConnectionMode } from "@/components/Canvas/mobileWorkflowTreeConnections";

interface Props {
  open: boolean;
  node: WorkflowNode | null;
  nodes: WorkflowNode[];
  initialAnchorId?: string | null;
  initialMode?: MobileWorkflowConnectionMode;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (event: "close"): void;
  (event: "connect", payload: { anchorId: string; mode: MobileWorkflowConnectionMode }): void;
}>();

const mode = ref<MobileWorkflowConnectionMode>("after");
const anchorId = ref<string | null>(null);
const query = ref("");
const candidates = computed(() => {
  const normalizedQuery = query.value.trim().toLowerCase();
  return props.nodes
    .filter((node) => node.id !== props.node?.id)
    .filter((node) => mode.value === "before" || node.type !== "output" || node.data.allowDownstream === true)
    .filter((node) => {
      const label = String(node.data.label || NODE_DEFINITIONS[node.type].label).toLowerCase();
      return !normalizedQuery || label.includes(normalizedQuery);
    })
    .sort((left, right) => left.position.y - right.position.y || left.position.x - right.position.x);
});
const modeLabel = computed(() => ({
  after: "after",
  before: "before",
  parallel: "as a parallel branch from",
})[mode.value]);

watch(
  () => [props.open, props.node?.id, props.initialAnchorId, props.initialMode],
  ([open, _nodeId, initialAnchorId, initialMode]) => {
    if (!open) return;
    mode.value = initialMode === "before" || initialMode === "parallel" ? initialMode : "after";
    anchorId.value = props.nodes.some(
      (node) =>
        node.id === initialAnchorId &&
        (mode.value === "before" || canConnectAfter(node)),
    )
      ? initialAnchorId as string
      : null;
    query.value = "";
  },
);

watch(mode, () => {
  if (!anchorId.value) return;
  const anchor = props.nodes.find((node) => node.id === anchorId.value);
  if (anchor && (mode.value === "before" || canConnectAfter(anchor))) return;
  anchorId.value = null;
});

function canConnectAfter(node: WorkflowNode): boolean {
  return node.type !== "output" || node.data.allowDownstream === true;
}

function nodeLabel(node: WorkflowNode): string {
  return String(node.data.label || NODE_DEFINITIONS[node.type].label);
}

function submit(): void {
  if (!anchorId.value) return;
  const anchor = props.nodes.find((node) => node.id === anchorId.value);
  if (!anchor || (mode.value !== "before" && !canConnectAfter(anchor))) return;
  emit("connect", { anchorId: anchorId.value, mode: mode.value });
}
</script>

<template>
  <Teleport to="body">
    <Transition name="mobile-connect-sheet">
      <div
        v-if="open && node"
        class="fixed inset-0 z-[104] flex items-end"
        role="dialog"
        aria-modal="true"
        aria-label="Connect workflow node"
      >
        <button
          type="button"
          class="absolute inset-0 bg-slate-950/45 backdrop-blur-[1px]"
          aria-label="Close node connection"
          @click="emit('close')"
        />
        <section class="relative z-10 flex max-h-[82dvh] w-full flex-col rounded-t-2xl border border-border/70 bg-card shadow-2xl">
          <div class="flex items-center justify-between px-4 pb-2 pt-3">
            <span class="mx-auto h-1 w-10 rounded-full bg-border" />
            <button
              type="button"
              class="absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Close node connection"
              @click="emit('close')"
            >
              <X class="h-4 w-4" />
            </button>
          </div>
          <div class="border-b border-border/60 px-4 pb-3">
            <p class="text-sm font-semibold">
              Connect {{ nodeLabel(node) }}
            </p>
            <p class="mt-1 text-xs text-muted-foreground">
              Choose where this node belongs in the workflow.
            </p>
          </div>
          <div class="grid grid-cols-3 gap-1.5 border-b border-border/60 p-3">
            <button
              v-for="option in ([
                ['after', 'After'],
                ['before', 'Before'],
                ['parallel', 'Parallel'],
              ] as const)"
              :key="option[0]"
              type="button"
              class="rounded-lg border px-2 py-2 text-xs font-medium transition-colors"
              :class="mode === option[0] ? 'border-violet-400/50 bg-violet-500/15 text-violet-700 dark:text-violet-200' : 'border-border/70 text-muted-foreground'"
              @click="mode = option[0]"
            >
              <GitBranch
                v-if="option[0] === 'parallel'"
                class="mx-auto mb-1 h-3.5 w-3.5"
              />
              {{ option[1] }}
            </button>
          </div>
          <div class="p-3 pb-0">
            <div class="flex h-9 items-center gap-2 rounded-lg border border-border/70 bg-background px-2">
              <Search class="h-4 w-4 text-muted-foreground" />
              <input
                v-model="query"
                class="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                placeholder="Find a node..."
                aria-label="Find workflow node"
              >
            </div>
          </div>
          <div class="min-h-0 flex-1 space-y-1 overflow-y-auto p-3">
            <button
              v-for="candidate in candidates"
              :key="candidate.id"
              type="button"
              class="flex w-full items-center gap-2 rounded-lg border p-2 text-left transition-colors"
              :class="anchorId === candidate.id ? 'border-violet-400/50 bg-violet-500/10' : 'border-border/60 bg-background hover:border-primary/40'"
              @click="anchorId = candidate.id"
            >
              <span
                class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted"
                :class="nodeIconColorClass[candidate.type]"
              >
                <component
                  :is="nodeIcons[candidate.type]"
                  :class="isTileFillingIcon(candidate.type) ? 'h-full w-full' : 'h-3.5 w-3.5'"
                />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-xs font-semibold">{{ nodeLabel(candidate) }}</span>
                <span class="block truncate text-[10px] text-muted-foreground">{{ NODE_DEFINITIONS[candidate.type].label }}</span>
              </span>
              <Check
                v-if="anchorId === candidate.id"
                class="h-4 w-4 shrink-0 text-violet-500"
              />
            </button>
          </div>
          <div class="border-t border-border/60 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            <button
              type="button"
              class="h-11 w-full rounded-lg bg-primary text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-45"
              :disabled="!anchorId"
              @click="submit"
            >
              Place {{ modeLabel }} selected node
            </button>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.mobile-connect-sheet-enter-active,
.mobile-connect-sheet-leave-active { transition: opacity 0.2s ease; }
.mobile-connect-sheet-enter-from,
.mobile-connect-sheet-leave-to { opacity: 0; }
.mobile-connect-sheet-enter-active section { animation: mobile-connect-sheet-slide 0.24s ease-out; }
@keyframes mobile-connect-sheet-slide { from { transform: translateY(18px); } to { transform: translateY(0); } }
</style>
