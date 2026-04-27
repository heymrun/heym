<script setup lang="ts">
import { computed } from "vue";
import { ArrowRight, MessageSquare, User, Wrench } from "lucide-vue-next";

export interface TraceSpan {
  id: string;
  label: string;
  durationMs: number;
  depth: number;
  icon: "invocation" | "agent" | "llm" | "tool";
}

const props = defineProps<{
  spans: TraceSpan[];
}>();

const maxDuration = computed(() => {
  if (props.spans.length === 0) return 1;
  return Math.max(...props.spans.map((s) => s.durationMs), 1);
});

function barWidthPercent(span: TraceSpan): number {
  return Math.min(100, (span.durationMs / maxDuration.value) * 100);
}

function formatDuration(ms: number): string {
  return `${ms.toFixed(2)}ms`;
}

const iconComponent = (icon: TraceSpan["icon"]) => {
  switch (icon) {
    case "invocation":
      return ArrowRight;
    case "agent":
      return User;
    case "llm":
      return MessageSquare;
    case "tool":
      return Wrench;
    default:
      return ArrowRight;
  }
};
</script>

<template>
  <div class="space-y-2">
    <div class="text-sm font-medium">
      Duration Breakdown
    </div>
    <div class="space-y-1.5">
      <div
        v-for="span in spans"
        :key="span.id"
        class="flex items-center gap-3 text-sm"
        :style="{ paddingLeft: `${span.depth * 16}px` }"
      >
        <component
          :is="iconComponent(span.icon)"
          class="w-4 h-4 shrink-0 text-muted-foreground"
        />
        <span class="min-w-0 truncate text-muted-foreground">
          {{ span.label }}
        </span>
        <span class="shrink-0 text-muted-foreground tabular-nums">
          {{ formatDuration(span.durationMs) }}
        </span>
        <div class="min-w-[80px] flex-1">
          <div
            class="h-2 rounded bg-primary/20 overflow-hidden"
            role="presentation"
          >
            <div
              class="h-full rounded bg-primary transition-all"
              :style="{ width: `${barWidthPercent(span)}%` }"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
