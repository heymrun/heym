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
const pendingReviewCount = computed(
  (): number => executions.value.filter((item) => item.status === "pending").length,
);
const runningCount = computed(
  (): number => activeWorkflowCount.value - pendingReviewCount.value,
);
const badgeTitle = computed((): string => {
  if (refreshFailed.value) {
    return activeWorkflowCount.value > 0
      ? `${activeWorkflowCount.value} active · Latest refresh failed`
      : "Active workflows unavailable";
  }
  if (activeWorkflowCount.value === 0) {
    return "No active workflows";
  }
  const parts: string[] = [];
  if (runningCount.value > 0) {
    parts.push(
      `${runningCount.value} running`,
    );
  }
  if (pendingReviewCount.value > 0) {
    parts.push(
      `${pendingReviewCount.value} pending review${pendingReviewCount.value === 1 ? "" : "s"}`,
    );
  }
  return parts.join(" · ");
});
const badgeAriaLabel = computed((): string => {
  const summary = badgeTitle.value;
  return `${summary}. Open live workflow list`;
});
const hasPendingOnly = computed(
  (): boolean => pendingReviewCount.value > 0 && runningCount.value === 0,
);

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
      {{ badgeTitle }}
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
          class="active-workflows-badge group relative flex items-center justify-center text-xs font-bold tabular-nums shadow-sm outline-none transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          :class="hasPendingOnly
            ? 'border border-amber-500/40 bg-amber-500/12 text-amber-700 shadow-amber-500/10 hover:border-amber-500/55 hover:bg-amber-500/18 focus-visible:ring-amber-500/45 dark:text-amber-300'
            : 'border border-emerald-500/35 bg-emerald-500/12 text-emerald-700 shadow-emerald-500/10 hover:border-emerald-500/55 hover:bg-emerald-500/18 focus-visible:ring-emerald-500/45 dark:text-emerald-300'"
          :aria-label="badgeAriaLabel"
          :title="badgeTitle"
          data-testid="active-workflows-badge"
        >
          {{ activeWorkflowCount }}
          <span class="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5">
            <span
              class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 motion-reduce:animate-none"
              :class="hasPendingOnly ? 'bg-amber-400' : 'bg-emerald-400'"
            />
            <span
              class="relative inline-flex h-2.5 w-2.5 rounded-full ring-2 ring-background"
              :class="hasPendingOnly ? 'bg-amber-500' : 'bg-emerald-500'"
            />
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
