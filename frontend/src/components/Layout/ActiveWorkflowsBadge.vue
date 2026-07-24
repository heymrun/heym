<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { useMediaQuery } from "@vueuse/core";
import { CircleAlert, LoaderCircle } from "lucide-vue-next";
import { DropdownMenuRoot, DropdownMenuTrigger } from "radix-vue";
import { useRouter } from "vue-router";

import type { ActiveExecutionItem } from "@/types/workflow";
import ActiveWorkflowsDropdown from "@/components/Layout/ActiveWorkflowsDropdown.vue";
import { workflowApi } from "@/services/api";

const POLL_INTERVAL_MS = 10_000;

const router = useRouter();
const isDesktop = useMediaQuery("(min-width: 768px)");
const executions = ref<ActiveExecutionItem[]>([]);
const isOpen = ref(false);
const hasLoaded = ref(false);
const isInitialLoading = ref(false);
const refreshFailed = ref(false);

let pollingInterval: number | null = null;
let requestInFlight = false;
let requestGeneration = 0;
let isUnmounted = false;

const activeWorkflowCount = computed((): number => executions.value.length);
const badgeTitle = computed((): string => {
  if (refreshFailed.value) {
    return activeWorkflowCount.value > 0
      ? `${activeWorkflowCount.value} active workflows · Latest refresh failed`
      : "Active workflows unavailable";
  }
  if (activeWorkflowCount.value === 0) {
    return "No active workflows";
  }
  return `${activeWorkflowCount.value} active workflows`;
});

async function refreshActiveWorkflows(): Promise<void> {
  if (!isDesktop.value || requestInFlight) return;

  requestInFlight = true;
  const generation = ++requestGeneration;
  if (!hasLoaded.value) {
    isInitialLoading.value = true;
  }

  try {
    const response = await workflowApi.getActiveExecutions();
    if (isUnmounted || generation !== requestGeneration || !isDesktop.value) return;
    executions.value = response;
    hasLoaded.value = true;
    refreshFailed.value = false;
  } catch {
    if (isUnmounted || generation !== requestGeneration || !isDesktop.value) return;
    refreshFailed.value = true;
  } finally {
    requestInFlight = false;
    if (generation === requestGeneration) {
      isInitialLoading.value = false;
    }
  }
}

function stopPolling(): void {
  if (pollingInterval !== null) {
    window.clearInterval(pollingInterval);
    pollingInterval = null;
  }
  requestGeneration += 1;
}

function startPolling(): void {
  stopPolling();
  void refreshActiveWorkflows();
  pollingInterval = window.setInterval(() => {
    void refreshActiveWorkflows();
  }, POLL_INTERVAL_MS);
}

function openLiveWorkflow(workflow: ActiveExecutionItem): void {
  isOpen.value = false;
  void router.push({
    name: "editor",
    params: {
      id: workflow.workflow_id,
      executionId: workflow.execution_id,
    },
  });
}

watch(
  isDesktop,
  (desktop) => {
    if (desktop) {
      startPolling();
      return;
    }
    isOpen.value = false;
    stopPolling();
  },
  { immediate: true },
);

watch(activeWorkflowCount, (count) => {
  if (count === 0) {
    isOpen.value = false;
  }
});

onUnmounted(() => {
  isUnmounted = true;
  stopPolling();
});
</script>

<template>
  <div
    v-if="isDesktop"
    class="relative flex items-center"
    data-testid="active-workflows-counter"
  >
    <span
      class="sr-only"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {{ activeWorkflowCount }} active workflows
    </span>

    <span
      v-if="isInitialLoading"
      class="flex h-9 w-9 items-center justify-center rounded-full border border-border/70 bg-muted/40 text-muted-foreground"
      aria-label="Loading active workflows"
      title="Loading active workflows"
      data-testid="active-workflows-badge-loading"
    >
      <LoaderCircle class="h-4 w-4 animate-spin" />
    </span>

    <span
      v-else-if="refreshFailed && !hasLoaded"
      class="flex h-9 w-9 items-center justify-center rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400"
      aria-label="Active workflows unavailable"
      title="Active workflows unavailable"
      data-testid="active-workflows-badge-error"
    >
      <CircleAlert class="h-4 w-4" />
    </span>

    <DropdownMenuRoot
      v-else-if="activeWorkflowCount > 0"
      v-model:open="isOpen"
    >
      <DropdownMenuTrigger as-child>
        <button
          type="button"
          class="active-workflows-badge group relative flex items-center justify-center border border-emerald-500/35 bg-emerald-500/12 text-xs font-bold tabular-nums text-emerald-700 shadow-sm shadow-emerald-500/10 outline-none transition-all duration-200 hover:-translate-y-0.5 hover:border-emerald-500/55 hover:bg-emerald-500/18 hover:shadow-md focus-visible:ring-2 focus-visible:ring-emerald-500/45 focus-visible:ring-offset-2 focus-visible:ring-offset-background dark:text-emerald-300"
          :aria-label="`${activeWorkflowCount} active workflows. Open live workflow list`"
          :title="badgeTitle"
          data-testid="active-workflows-badge"
        >
          {{ activeWorkflowCount }}
          <span class="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5">
            <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:animate-none" />
            <span class="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500 ring-2 ring-background" />
          </span>
        </button>
      </DropdownMenuTrigger>

      <ActiveWorkflowsDropdown
        :workflows="executions"
        :refresh-failed="refreshFailed"
        @select="openLiveWorkflow"
      />
    </DropdownMenuRoot>
  </div>
</template>

<style scoped>
.active-workflows-badge {
  aspect-ratio: 1 / 1;
  block-size: 2.25rem;
  flex: 0 0 2.25rem;
  inline-size: 2.25rem;
  border-radius: 50%;
}
</style>
