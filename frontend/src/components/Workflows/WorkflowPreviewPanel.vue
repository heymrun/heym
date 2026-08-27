<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  History,
  LoaderCircle,
  MousePointerClick,
  Play,
  Settings,
  Workflow as WorkflowIcon,
  Zap,
} from "lucide-vue-next";

import type { AllExecutionHistoryEntryLight, Workflow, WorkflowListItem } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import { isTileFillingIcon, nodeIcons } from "@/lib/nodeIcons";
import { cn, formatDate } from "@/lib/utils";
import { orderWorkflowSteps, summarizeTrigger } from "@/lib/workflowPreview";

interface Props {
  /** Listing row for the selection - always available, so the header renders instantly. */
  summary: WorkflowListItem | null;
  /** Full workflow, loaded lazily; null while the request is in flight. */
  detail: Workflow | null;
  lastRun: AllExecutionHistoryEntryLight | null;
  loading?: boolean;
  error?: string | null;
  running?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  error: null,
  running: false,
});

const emit = defineEmits<{
  goToWorkflow: [id: string, event: MouseEvent];
  run: [id: string];
  openHistory: [id: string];
  openStep: [nodeId: string];
}>();

const iconComponent = computed(() => {
  const type = props.summary?.first_node_type;
  return type && nodeIcons[type] ? nodeIcons[type] : WorkflowIcon;
});

const iconFillsTile = computed((): boolean => {
  const type = props.summary?.first_node_type;
  return !!type && isTileFillingIcon(type);
});

/** A save always lands a hair after creation, so only a real later edit counts as one. */
const EDITED_THRESHOLD_MS = 60_000;

/** Short enough for the header row; the dates live in the hover title. */
const metaLine = computed((): string => {
  if (!props.summary) return "";
  const owner = props.detail?.owner_name;
  return owner ? `Created by ${owner}` : `Created ${formatDate(props.summary.created_at)}`;
});

const metaTooltip = computed((): string => {
  if (!props.summary) return "";
  const owner = props.detail?.owner_name;
  const parts = [`Created ${formatDate(props.summary.created_at)}${owner ? ` by ${owner}` : ""}`];

  const createdAt = Date.parse(props.summary.created_at);
  const updatedAt = Date.parse(props.summary.updated_at);
  if (Number.isFinite(createdAt) && Number.isFinite(updatedAt)
    && updatedAt - createdAt > EDITED_THRESHOLD_MS) {
    parts.push(`Edited ${formatDate(props.summary.updated_at)}`);
  }

  return parts.join(" · ");
});

const trigger = computed(() => (props.detail ? summarizeTrigger(props.detail) : null));

const steps = computed(() =>
  props.detail ? orderWorkflowSteps(props.detail.nodes, props.detail.edges) : [],
);

const lastRunSucceeded = computed((): boolean => props.lastRun?.status === "success");

const lastRunHeadline = computed((): string => {
  if (!props.lastRun) return "No runs yet";
  const seconds = (props.lastRun.execution_time_ms / 1000).toFixed(1);
  const verb = lastRunSucceeded.value ? "Completed successfully" : `Finished as ${props.lastRun.status}`;
  return `${verb} in ${seconds}s`;
});

const lastRunDetail = computed((): string => {
  if (!props.lastRun) return "Run it once to see timing here";
  const source = props.lastRun.trigger_source ? `${props.lastRun.trigger_source} · ` : "";
  return `${source}${formatDate(props.lastRun.started_at)}`;
});

const curlCopied = ref(false);
let curlCopiedTimer: ReturnType<typeof setTimeout> | null = null;

async function copyCurl(): Promise<void> {
  const command = trigger.value?.curl;
  if (!command) return;
  try {
    await navigator.clipboard.writeText(command);
  } catch {
    return;
  }
  curlCopied.value = true;
  if (curlCopiedTimer) clearTimeout(curlCopiedTimer);
  curlCopiedTimer = setTimeout(() => {
    curlCopied.value = false;
  }, 2000);
}

onUnmounted(() => {
  if (curlCopiedTimer) clearTimeout(curlCopiedTimer);
});
</script>

<template>
  <div
    class="flex h-full min-h-0 flex-1 flex-col"
    data-testid="workflow-preview-panel"
  >
    <div
      v-if="!summary"
      class="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-16 text-center"
    >
      <MousePointerClick class="h-9 w-9 text-muted-foreground/40" />
      <p class="text-sm font-medium text-foreground">
        Select a workflow
      </p>
      <p class="max-w-xs text-xs text-muted-foreground">
        Pick a workflow on the left to see its trigger, last run and steps here.
      </p>
    </div>

    <template v-else>
      <div class="flex flex-wrap items-start gap-3 border-b border-border/60 px-4 py-4 sm:px-6">
        <div class="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-primary dark:text-brand-primary-soft">
          <div class="absolute inset-0 rounded-xl bg-gradient-to-br from-primary/15 via-primary/10 to-primary/5 dark:from-primary/[0.14] dark:via-primary/[0.08] dark:to-transparent" />
          <div class="absolute inset-0 rounded-xl ring-1 ring-inset ring-primary/20 dark:ring-primary/25" />
          <component
            :is="iconComponent"
            :class="iconFillsTile ? 'relative z-10 h-full w-full' : 'relative z-10 h-5 w-5'"
          />
        </div>

        <div class="min-w-0 flex-1">
          <h2
            class="truncate text-base font-semibold leading-tight"
            data-testid="workflow-preview-title"
            :title="summary.name"
          >
            {{ summary.name }}
          </h2>
          <p
            class="mt-1 truncate text-xs text-muted-foreground"
            :title="metaTooltip"
          >
            {{ metaLine }}
          </p>
        </div>

        <div class="flex w-full shrink-0 items-center gap-2 sm:w-auto">
          <Button
            variant="outline"
            size="sm"
            class="flex-1 sm:flex-none"
            data-testid="workflow-preview-goto"
            @click="emit('goToWorkflow', summary.id, $event)"
          >
            <ExternalLink class="h-3.5 w-3.5" />
            Open Workflow
          </Button>
          <Button
            variant="gradient"
            size="sm"
            class="flex-1 sm:flex-none"
            data-testid="workflow-preview-run"
            @click="emit('run', summary.id)"
          >
            <Play class="h-3.5 w-3.5" />
            Run Now
          </Button>
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div
          v-if="error"
          class="mb-5 flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs text-destructive"
        >
          <AlertTriangle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{{ error }}</span>
        </div>

        <section class="mb-6">
          <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Description
          </h3>
          <p class="text-sm leading-relaxed text-muted-foreground">
            {{ summary.description || "No description yet." }}
          </p>
        </section>

        <div class="mb-6 grid grid-cols-1 items-stretch gap-3 md:grid-cols-2">
          <div class="flex h-full flex-col rounded-xl border border-border/60 bg-muted/25 px-4 pb-2.5 pt-3.5">
            <div class="mb-2.5 flex items-center gap-2 text-xs font-semibold">
              <Zap class="h-3.5 w-3.5 text-amber-500" />
              Trigger Configuration
            </div>
            <div class="flex flex-1 flex-col justify-start">
              <p
                v-if="loading && !trigger"
                class="h-4 w-2/3 animate-pulse rounded bg-muted"
              />
              <template v-else>
                <!--
                  Two buttons pair off as label/button rows on a shared grid so the labels
                  and the buttons each line up. A single button just stacks under its label.
                -->
                <div
                  v-if="trigger?.portalUrl"
                  class="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2"
                >
                  <p class="flex min-h-[30px] items-center break-words text-[13px] font-medium">
                    {{ trigger.headline }}
                  </p>
                  <button
                    v-if="trigger.curl"
                    type="button"
                    class="inline-flex w-fit shrink-0 items-center gap-1.5 rounded-md border border-border/70 bg-background px-2.5 py-1.5 text-xs font-medium transition-colors hover:border-border hover:bg-muted/60 justify-self-start"
                    data-testid="workflow-preview-copy-curl"
                    @click="copyCurl"
                  >
                    <Check
                      v-if="curlCopied"
                      class="h-3 w-3 text-emerald-500"
                    />
                    <Copy
                      v-else
                      class="h-3 w-3"
                    />
                    {{ curlCopied ? "Copied" : "Copy cURL" }}
                  </button>
                  <span
                    v-else
                    aria-hidden="true"
                  />

                  <p class="flex min-h-[30px] items-center break-words text-[13px] font-medium">
                    Portal
                  </p>
                  <a
                    :href="trigger.portalUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-flex w-fit shrink-0 items-center gap-1.5 rounded-md border border-border/70 bg-background px-2.5 py-1.5 text-xs font-medium transition-colors hover:border-border hover:bg-muted/60 justify-self-start"
                    data-testid="workflow-preview-portal-link"
                    :title="trigger.portalUrl"
                  >
                    <ExternalLink class="h-3 w-3 shrink-0" />
                    Open
                  </a>
                </div>

                <div
                  v-else
                  class="flex flex-col items-start gap-2"
                >
                  <p class="flex min-h-[30px] items-center break-words text-[13px] font-medium">
                    {{ trigger?.headline ?? "Unavailable" }}
                  </p>
                  <button
                    v-if="trigger?.curl"
                    type="button"
                    class="inline-flex w-fit shrink-0 items-center gap-1.5 rounded-md border border-border/70 bg-background px-2.5 py-1.5 text-xs font-medium transition-colors hover:border-border hover:bg-muted/60"
                    data-testid="workflow-preview-copy-curl"
                    @click="copyCurl"
                  >
                    <Check
                      v-if="curlCopied"
                      class="h-3 w-3 text-emerald-500"
                    />
                    <Copy
                      v-else
                      class="h-3 w-3"
                    />
                    {{ curlCopied ? "Copied" : "Copy cURL" }}
                  </button>
                </div>
                <p
                  v-if="trigger?.detail"
                  class="mt-2 text-xs text-muted-foreground"
                >
                  {{ trigger.detail }}
                </p>
              </template>
            </div>
          </div>

          <div class="flex h-full flex-col rounded-xl border border-border/60 bg-muted/25 px-4 pb-2.5 pt-3.5">
            <div class="mb-2.5 flex items-center justify-between gap-2 text-xs font-semibold">
              <div class="flex items-center gap-2">
                <CheckCircle2
                  class="h-3.5 w-3.5"
                  :class="lastRunSucceeded ? 'text-emerald-500' : 'text-muted-foreground'"
                />
                Last Run Details
              </div>
              <!-- Negative margin keeps the 28px control from growing the 16px header row. -->
              <button
                type="button"
                class="-my-1.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                title="Execution history"
                aria-label="Execution history"
                data-testid="workflow-preview-history"
                @click="emit('openHistory', summary.id)"
              >
                <History class="h-3.5 w-3.5" />
              </button>
            </div>
            <div class="flex flex-1 flex-col justify-start">
              <p
                v-if="loading && !lastRun"
                class="h-4 w-2/3 animate-pulse rounded bg-muted"
              />
              <template v-else>
                <p class="flex min-h-[30px] items-center break-words text-[13px] font-medium">
                  {{ lastRunHeadline }}
                </p>
                <p class="mt-2 text-xs text-muted-foreground">
                  {{ lastRunDetail }}
                </p>
              </template>
            </div>
          </div>
        </div>

        <section>
          <h3 class="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Workflow Steps &amp; Sub-agents ({{ steps.length }})
          </h3>

          <div
            v-if="loading && steps.length === 0"
            class="space-y-2"
          >
            <div
              v-for="i in 3"
              :key="i"
              class="h-[54px] animate-pulse rounded-xl bg-muted/60"
            />
          </div>

          <p
            v-else-if="steps.length === 0"
            class="rounded-xl border border-dashed border-border/60 px-4 py-6 text-center text-xs text-muted-foreground"
          >
            This workflow has no nodes yet.
          </p>

          <ul
            v-else
            class="space-y-2"
          >
            <li
              v-for="step in steps"
              :key="step.id"
            >
              <button
                type="button"
                :class="cn(
                  'flex w-full items-center gap-3 rounded-xl border border-border/50 bg-card px-4 py-3 text-left transition-all',
                  'hover:border-border hover:bg-muted/40',
                )"
                :data-testid="`workflow-preview-step-${step.order}`"
                @click="emit('openStep', step.id)"
              >
                <span class="w-6 shrink-0 text-xs font-semibold tabular-nums text-muted-foreground/70">
                  {{ String(step.order).padStart(2, "0") }}
                </span>
                <span class="min-w-0 flex-1">
                  <span
                    class="block truncate text-[13px] font-medium"
                    :title="step.title"
                  >{{ step.title }}</span>
                  <span
                    class="block truncate text-[11px] text-muted-foreground"
                    :title="step.subtitle"
                  >{{ step.subtitle }}</span>
                </span>
                <span
                  :class="cn(
                    'h-1.5 w-1.5 shrink-0 rounded-full',
                    step.active ? 'bg-emerald-500' : 'bg-muted-foreground/40',
                  )"
                  :title="step.active ? 'Active' : 'Deactivated'"
                />
                <Settings class="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
              </button>
            </li>
          </ul>
        </section>
      </div>

      <div
        v-if="running"
        class="flex items-center gap-2 border-t border-border/60 px-4 py-2.5 text-xs text-muted-foreground sm:px-6"
      >
        <LoaderCircle class="h-3.5 w-3.5 animate-spin text-primary" />
        This workflow is running right now.
      </div>
    </template>
  </div>
</template>
