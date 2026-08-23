<script setup lang="ts">
import { computed } from "vue";

import type { WorkflowRowStatus } from "@/types/workflow";
import { cn } from "@/lib/utils";

interface Props {
  status: WorkflowRowStatus;
  /** Smaller variant for nested folder rows. */
  compact?: boolean;
}

const props = withDefaults(defineProps<Props>(), { compact: false });

interface StatusStyle {
  label: string;
  badge: string;
  dot: string;
  pulse: boolean;
}

const STATUS_STYLES: Record<WorkflowRowStatus, StatusStyle> = {
  running: {
    label: "Running",
    badge: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20",
    dot: "bg-emerald-500",
    pulse: true,
  },
  scheduled: {
    label: "Scheduled",
    badge: "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20",
    dot: "bg-amber-500",
    pulse: false,
  },
  listening: {
    label: "Listening",
    badge: "bg-sky-500/10 text-sky-600 dark:text-sky-400 ring-sky-500/20",
    dot: "bg-sky-500",
    pulse: false,
  },
  paused: {
    label: "Paused",
    badge: "bg-muted text-muted-foreground ring-border/60",
    dot: "bg-muted-foreground/60",
    pulse: false,
  },
  manual: {
    label: "Manual",
    badge: "bg-muted/60 text-muted-foreground ring-border/50",
    dot: "bg-muted-foreground/50",
    pulse: false,
  },
  api: {
    label: "API",
    badge: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 ring-indigo-500/20",
    dot: "bg-indigo-500",
    pulse: false,
  },
  subWorkflow: {
    label: "SubWorker",
    badge: "bg-violet-500/10 text-violet-600 dark:text-violet-400 ring-violet-500/20",
    dot: "bg-violet-500",
    pulse: false,
  },
  portal: {
    label: "Portal",
    badge: "bg-teal-500/10 text-teal-600 dark:text-teal-400 ring-teal-500/20",
    dot: "bg-teal-500",
    pulse: false,
  },
  web: {
    label: "WEB",
    badge: "bg-rose-500/10 text-rose-600 dark:text-rose-400 ring-rose-500/20",
    dot: "bg-rose-500",
    pulse: false,
  },
  removeScheduled: {
    label: "Remove Scheduled",
    badge:
      "bg-destructive/10 text-destructive ring-destructive/20",
    dot: "bg-destructive",
    pulse: false,
  },
};

const style = computed((): StatusStyle => STATUS_STYLES[props.status]);
</script>

<template>
  <span
    :class="cn(
      'inline-flex shrink-0 items-center gap-1.5 rounded-full font-medium ring-1 ring-inset',
      compact ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-[11px]',
      style.badge,
    )"
    :data-status="status"
  >
    <span class="relative flex h-1.5 w-1.5 shrink-0">
      <span
        v-if="style.pulse"
        :class="cn('absolute inline-flex h-full w-full animate-ping rounded-full opacity-60', style.dot)"
      />
      <span :class="cn('relative inline-flex h-1.5 w-1.5 rounded-full', style.dot)" />
    </span>
    {{ style.label }}
  </span>
</template>
