<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { AlertCircle, Check, CheckCircle2, ChevronLeft, ChevronRight, Copy, Settings2, X } from "lucide-vue-next";

import JsonTree from "@/components/ui/JsonTree.vue";
import { isTileFillingIcon, nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";
import { NODE_DEFINITIONS } from "@/types/node";
import type { NodeResult, WorkflowNode } from "@/types/workflow";

interface Props {
  open: boolean;
  result: NodeResult | null;
  node: WorkflowNode | null;
  output: unknown;
  workflowName: string;
  previousNodeLabel?: string | null;
  nextNodeLabel?: string | null;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  close: [];
  properties: [];
  previous: [];
  next: [];
}>();

type DetailTab = "input" | "output" | "errors";

const activeTab = ref<DetailTab>("output");
const copied = ref(false);
const detailRef = ref<HTMLElement | null>(null);

const nodeIcon = computed(() => (props.node ? nodeIcons[props.node.type] : AlertCircle));
const nodeIconClass = computed(() =>
  props.node ? nodeIconColorClass[props.node.type] : "text-muted-foreground",
);
const nodeName = computed(
  () => props.node?.data.label || props.result?.node_label || "Workflow node",
);
const nodeType = computed(() => {
  if (props.node) return NODE_DEFINITIONS[props.node.type].label;
  return props.result?.node_type || "Node";
});
const status = computed(() => props.result?.status || "pending");
const statusLabel = computed(() => status.value.replace(/_/g, " "));
const statusClass = computed(() => {
  if (status.value === "success") return "text-emerald-500";
  if (status.value === "error") return "text-destructive";
  if (status.value === "skipped") return "text-muted-foreground";
  return "text-amber-500";
});
const statusBadgeClass = computed(() => {
  if (status.value === "success") return "bg-emerald-500/10 text-emerald-500";
  if (status.value === "error") return "bg-destructive/10 text-destructive";
  if (status.value === "skipped") return "bg-muted text-muted-foreground";
  return "bg-amber-500/10 text-amber-500";
});
const outputFormat = computed(() =>
  props.output !== null && typeof props.output === "object" ? "application/json" : "text/plain",
);
const displayOutput = computed(() => sanitizeOutputForDetail(props.output));
const nodeConfiguration = computed(() => props.node?.data ?? {});

function sanitizeOutputForDetail(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (typeof value === "string") {
    if (value.startsWith("data:image/") && value.length > 100) {
      return "[Image data – base64]";
    }
    if (value.length > 100 && /^[A-Za-z0-9+/=]+$/.test(value)) {
      return "[Base64 data]";
    }
    return value;
  }
  if (Array.isArray(value)) return value.map(sanitizeOutputForDetail);
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, sanitizeOutputForDetail(item)]),
    );
  }
  return value;
}

function formatDuration(durationMs: number | undefined): string {
  if (!durationMs || durationMs < 1_000) return `${Math.round(durationMs ?? 0)}ms`;
  return `${(durationMs / 1_000).toFixed(2)}s`;
}

async function copyOutput(): Promise<void> {
  if (props.output === undefined) return;

  try {
    const text =
      typeof props.output === "string"
        ? props.output
        : JSON.stringify(props.output, null, 2);
    await navigator.clipboard.writeText(text);
    copied.value = true;
    window.setTimeout(() => {
      copied.value = false;
    }, 2_000);
  } catch {
    copied.value = false;
  }
}

function selectTab(tab: DetailTab): void {
  activeTab.value = tab;
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    activeTab.value = "output";
    copied.value = false;
    await nextTick();
    detailRef.value?.focus({ preventScroll: true });
  },
);
</script>

<template>
  <Teleport to="body">
    <Transition name="mobile-execution-detail">
      <section
        v-if="open && result"
        ref="detailRef"
        class="fixed inset-0 z-[70] flex h-[100dvh] flex-col overflow-hidden bg-background text-foreground md:hidden"
        role="dialog"
        aria-modal="true"
        aria-label="Node execution detail"
        tabindex="-1"
        @keydown.escape.stop.prevent="emit('close')"
      >
        <header class="flex h-16 shrink-0 items-center justify-between border-b border-border/60 bg-background px-4">
          <div class="flex min-w-0 items-center gap-2.5">
            <img
              src="/fav.svg"
              alt="Heym"
              class="h-8 w-8 shrink-0"
            >
            <div class="min-w-0">
              <p class="text-sm font-bold leading-4">
                Heym
              </p>
              <p
                class="max-w-40 truncate text-[11px] leading-4 text-muted-foreground"
                :title="workflowName"
              >
                {{ workflowName }}
              </p>
            </div>
          </div>
          <span
            class="rounded-md border border-violet-500/25 bg-violet-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-violet-600 dark:text-violet-300"
          >
            Node execution
          </span>
        </header>

        <div class="flex shrink-0 items-center justify-between border-b border-border/60 bg-background px-4 py-2.5">
          <div class="flex min-w-0 items-center gap-4 text-xs">
            <span class="inline-flex items-center gap-1.5 text-muted-foreground">
              <span
                class="h-2 w-2 rounded-full"
                :class="status === 'success' ? 'bg-emerald-500' : status === 'error' ? 'bg-destructive' : 'bg-amber-500'"
              />
              Status:
              <strong
                class="capitalize"
                :class="statusClass"
              >{{ statusLabel }}</strong>
            </span>
            <span class="text-muted-foreground">
              Duration:
              <strong class="font-semibold text-foreground">{{ formatDuration(result.execution_time_ms) }}</strong>
            </span>
          </div>
          <button
            type="button"
            class="-mr-2 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Close node execution detail"
            @click="emit('close')"
          >
            <X class="h-4 w-4" />
          </button>
        </div>

        <main class="min-h-0 flex-1 overflow-y-auto p-4">
          <div class="mx-auto flex min-h-full w-full max-w-md flex-col gap-4">
            <section class="flex items-center justify-between rounded-xl border border-border/60 bg-card p-4">
              <div class="flex min-w-0 items-center gap-3">
                <div
                  class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted/70"
                  :class="nodeIconClass"
                >
                  <component
                    :is="nodeIcon"
                    :class="isTileFillingIcon(node?.type ?? 'http') ? 'h-full w-full' : 'h-5 w-5'"
                  />
                </div>
                <div class="min-w-0">
                  <h1 class="truncate text-sm font-bold">
                    {{ nodeName }}
                  </h1>
                  <p class="truncate text-[11px] text-muted-foreground">
                    {{ nodeType }} · {{ result.node_id }}
                  </p>
                </div>
              </div>
              <div class="flex shrink-0 items-center gap-1">
                <button
                  v-if="previousNodeLabel"
                  type="button"
                  class="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  :aria-label="`Previous node: ${previousNodeLabel}`"
                  :title="`Previous: ${previousNodeLabel}`"
                  @click="emit('previous')"
                >
                  <ChevronLeft class="h-4 w-4" />
                </button>
                <span
                  class="rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wide"
                  :class="statusBadgeClass"
                >{{ statusLabel }}</span>
                <button
                  v-if="nextNodeLabel"
                  type="button"
                  class="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  :aria-label="`Next node: ${nextNodeLabel}`"
                  :title="`Next: ${nextNodeLabel}`"
                  @click="emit('next')"
                >
                  <ChevronRight class="h-4 w-4" />
                </button>
              </div>
            </section>

            <div
              class="grid h-9 grid-cols-3 rounded-lg bg-muted/60 p-0.5"
              role="tablist"
              aria-label="Node execution data"
            >
              <button
                type="button"
                class="rounded-md px-2 text-xs font-medium transition-colors"
                :class="activeTab === 'input' ? 'border border-border/60 bg-card text-foreground shadow-sm' : 'text-muted-foreground'"
                role="tab"
                :aria-selected="activeTab === 'input'"
                @click="selectTab('input')"
              >
                Input Data
              </button>
              <button
                type="button"
                class="rounded-md px-2 text-xs font-medium transition-colors"
                :class="activeTab === 'output' ? 'border border-border/60 bg-card text-foreground shadow-sm' : 'text-muted-foreground'"
                role="tab"
                :aria-selected="activeTab === 'output'"
                @click="selectTab('output')"
              >
                Output Data
              </button>
              <button
                type="button"
                class="rounded-md px-2 text-xs font-medium transition-colors"
                :class="activeTab === 'errors' ? 'border border-border/60 bg-card text-foreground shadow-sm' : 'text-muted-foreground'"
                role="tab"
                :aria-selected="activeTab === 'errors'"
                @click="selectTab('errors')"
              >
                Errors
              </button>
            </div>

            <section class="flex min-h-[22rem] flex-1 flex-col rounded-xl border border-border/60 bg-card p-4">
              <template v-if="activeTab === 'output'">
                <div class="flex items-center justify-between gap-3 pb-3 text-xs">
                  <span class="font-semibold text-muted-foreground">Response Payload</span>
                  <span class="font-mono text-[10px] text-muted-foreground">{{ outputFormat }}</span>
                </div>
                <div class="min-h-0 flex-1 overflow-auto rounded-lg bg-background/60 p-3 font-mono text-xs leading-5 select-text">
                  <JsonTree
                    v-if="displayOutput !== null && typeof displayOutput === 'object'"
                    :data="displayOutput"
                    :root-expanded="true"
                    :auto-expand-depth="3"
                  />
                  <pre
                    v-else
                    class="whitespace-pre-wrap break-words"
                  >{{ displayOutput ?? 'null' }}</pre>
                </div>
              </template>

              <template v-else-if="activeTab === 'input'">
                <div class="flex items-center justify-between gap-3 pb-3 text-xs">
                  <span class="font-semibold text-muted-foreground">Node Configuration</span>
                  <span class="font-mono text-[10px] text-muted-foreground">application/json</span>
                </div>
                <div class="min-h-0 flex-1 overflow-auto rounded-lg bg-background/60 p-3 font-mono text-xs leading-5 select-text">
                  <JsonTree
                    :data="nodeConfiguration"
                    :root-expanded="true"
                    :auto-expand-depth="2"
                  />
                </div>
              </template>

              <template v-else>
                <div class="flex items-center gap-2 pb-3 text-xs font-semibold text-muted-foreground">
                  <AlertCircle class="h-4 w-4" />
                  Execution Errors
                </div>
                <div
                  v-if="result.error"
                  class="rounded-lg border border-destructive/30 bg-destructive/10 p-3 font-mono text-xs leading-5 text-destructive whitespace-pre-wrap break-words select-text"
                >
                  {{ result.error }}
                </div>
                <div
                  v-else
                  class="flex flex-1 flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground"
                >
                  <CheckCircle2 class="h-7 w-7 text-emerald-500" />
                  No errors were reported for this node.
                </div>
              </template>
            </section>

            <section class="grid grid-cols-3 rounded-xl border border-border/60 bg-card p-3 text-center">
              <div class="border-r border-border/60 px-1">
                <p class="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Execution time
                </p>
                <p class="mt-1 font-mono text-xs font-bold">
                  {{ formatDuration(result.execution_time_ms) }}
                </p>
              </div>
              <div class="border-r border-border/60 px-1">
                <p class="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Node type
                </p>
                <p class="mt-1 truncate text-xs font-bold">
                  {{ nodeType }}
                </p>
              </div>
              <div class="px-1">
                <p class="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Result
                </p>
                <p
                  class="mt-1 truncate text-xs font-bold capitalize"
                  :class="statusClass"
                >
                  {{ statusLabel }}
                </p>
              </div>
            </section>
          </div>
        </main>

        <footer class="grid shrink-0 grid-cols-3 gap-2 border-t border-border/60 bg-card p-4">
          <button
            type="button"
            class="inline-flex h-10 items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-muted/60 px-2 text-xs font-semibold transition-colors hover:bg-muted"
            @click="copyOutput"
          >
            <Check
              v-if="copied"
              class="h-4 w-4 text-emerald-500"
            />
            <Copy
              v-else
              class="h-4 w-4"
            />
            {{ copied ? 'Copied' : 'Copy Output' }}
          </button>
          <button
            type="button"
            class="inline-flex h-10 items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-muted/60 px-2 text-xs font-semibold transition-colors hover:bg-muted"
            @click="emit('properties')"
          >
            <Settings2 class="h-4 w-4" />Properties
          </button>
          <button
            type="button"
            class="inline-flex h-10 items-center justify-center gap-1.5 rounded-lg bg-primary px-2 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
            @click="emit('close')"
          >
            Back to workflow
          </button>
        </footer>
      </section>
    </Transition>
  </Teleport>
</template>

<style scoped>
.mobile-execution-detail-enter-active,
.mobile-execution-detail-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.mobile-execution-detail-enter-from,
.mobile-execution-detail-leave-to {
  opacity: 0;
  transform: translateY(12px);
}
</style>
