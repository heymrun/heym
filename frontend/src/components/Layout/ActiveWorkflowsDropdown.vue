<script setup lang="ts">
import {
  DropdownMenuArrow,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
} from "radix-vue";
import { Activity, ArrowUpRight, CircleAlert } from "lucide-vue-next";

import type { ActiveExecutionItem } from "@/types/workflow";

interface Props {
  workflows: ActiveExecutionItem[];
  refreshFailed?: boolean;
}

withDefaults(defineProps<Props>(), {
  refreshFailed: false,
});

const emit = defineEmits<{
  (event: "select", workflow: ActiveExecutionItem): void;
}>();

const startedAtFormatter = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
});

function formatStartedAt(value: string): string {
  const startedAt = new Date(value);
  if (Number.isNaN(startedAt.getTime())) {
    return "Running now";
  }
  return `Started at ${startedAtFormatter.format(startedAt)}`;
}
</script>

<template>
  <DropdownMenuPortal>
    <DropdownMenuContent
      :side-offset="10"
      :collision-padding="12"
      align="end"
      class="active-workflows-dropdown z-[200] w-80 overflow-hidden rounded-2xl border border-border/70 bg-popover/95 text-popover-foreground shadow-2xl shadow-slate-950/15 backdrop-blur-xl"
      data-testid="active-workflows-dropdown"
    >
      <div class="flex items-center justify-between border-b border-border/60 px-4 py-3">
        <div class="flex items-center gap-2">
          <span class="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/12 text-emerald-600 dark:text-emerald-400">
            <Activity class="h-4 w-4" />
          </span>
          <div>
            <p class="text-sm font-semibold leading-tight">
              Active workflows
            </p>
            <p class="mt-0.5 text-[11px] leading-tight text-muted-foreground">
              Select a workflow to open its live view
            </p>
          </div>
        </div>
        <span class="rounded-full bg-emerald-500/12 px-2 py-0.5 text-xs font-semibold tabular-nums text-emerald-700 dark:text-emerald-300">
          {{ workflows.length }}
        </span>
      </div>

      <div
        v-if="refreshFailed"
        class="flex items-center gap-1.5 border-b border-amber-500/20 bg-amber-500/8 px-4 py-2 text-[11px] text-amber-700 dark:text-amber-300"
        role="status"
      >
        <CircleAlert class="h-3.5 w-3.5 shrink-0" />
        Showing the last successful update
      </div>

      <div
        class="active-workflows-scroll overflow-y-auto overscroll-contain p-1"
        data-testid="active-workflows-scroll-area"
      >
        <DropdownMenuItem
          v-for="workflow in workflows"
          :key="workflow.execution_id"
          class="group flex h-14 cursor-pointer select-none items-center gap-3 rounded-xl px-3 outline-none transition-colors data-[highlighted]:bg-emerald-500/10 data-[highlighted]:text-foreground"
          :aria-label="`Open ${workflow.workflow_name} live view`"
          :data-testid="`active-workflow-${workflow.execution_id}`"
          @select="emit('select', workflow)"
        >
          <span class="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <Activity class="h-4 w-4" />
            <span class="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-emerald-500 ring-2 ring-popover" />
          </span>
          <span class="min-w-0 flex-1">
            <span
              class="block truncate text-sm font-medium"
              :title="workflow.workflow_name"
            >
              {{ workflow.workflow_name }}
            </span>
            <span class="mt-0.5 block text-[11px] text-muted-foreground">
              {{ formatStartedAt(workflow.started_at) }}
            </span>
          </span>
          <ArrowUpRight class="h-4 w-4 shrink-0 text-muted-foreground/60 transition-colors group-data-[highlighted]:text-emerald-600 dark:group-data-[highlighted]:text-emerald-400" />
        </DropdownMenuItem>
      </div>

      <DropdownMenuArrow class="fill-popover stroke-border/70" />
    </DropdownMenuContent>
  </DropdownMenuPortal>
</template>

<style scoped>
.active-workflows-dropdown {
  transform-origin: var(--radix-dropdown-menu-content-transform-origin);
}

.active-workflows-dropdown[data-state="open"] {
  animation: active-workflows-open 180ms cubic-bezier(0.22, 1, 0.36, 1);
}

.active-workflows-dropdown[data-state="closed"] {
  animation: active-workflows-close 120ms ease-in;
}

.active-workflows-scroll {
  max-block-size: 14.5rem;
  scrollbar-color: hsl(var(--muted-foreground) / 0.35) transparent;
  scrollbar-width: thin;
}

@keyframes active-workflows-open {
  from {
    opacity: 0;
    transform: translateY(-6px) scale(0.97);
  }

  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes active-workflows-close {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }

  to {
    opacity: 0;
    transform: translateY(-3px) scale(0.98);
  }
}

@media (prefers-reduced-motion: reduce) {
  .active-workflows-dropdown[data-state] {
    animation: none;
  }
}
</style>
