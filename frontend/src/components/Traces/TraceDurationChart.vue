<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { ArrowRight, MessageSquare, Split, User, Wrench } from "lucide-vue-next";

import type { TraceSpan } from "@/types/trace";

const props = defineProps<{
  spans: TraceSpan[];
}>();

const router = useRouter();

const emit = defineEmits<{
  (e: "focusStep", stepId: string): void;
}>();

function isLinked(span: TraceSpan): boolean {
  return Boolean(span.traceId || span.stepId);
}

/**
 * The track is the whole request, and every row's track starts at the same x, so a
 * bar's position reads as its place in time rather than as an artefact of how long
 * the label beside it happened to be.
 */
const trackMs = computed(() => {
  if (props.spans.length === 0) return 1;
  return Math.max(...props.spans.map((s) => (s.startMs ?? 0) + s.durationMs), 1);
});

function barWidthPercent(span: TraceSpan): number {
  return Math.min(100, (span.durationMs / trackMs.value) * 100);
}

function barOffsetPercent(span: TraceSpan): number {
  const offset = ((span.startMs ?? 0) / trackMs.value) * 100;
  return Math.min(100 - barWidthPercent(span), Math.max(0, offset));
}

/**
 * A span that ran work of its own opens that run; a span that is part of this trace
 * has nowhere to navigate, so it takes you to its step instead.
 */
function activateSpan(span: TraceSpan, event: MouseEvent): void {
  event.stopPropagation();
  if (span.traceId) {
    const href = router.resolve({
      path: "/",
      query: { tab: "traces", traceId: span.traceId },
    }).href;
    window.open(href, "_blank", "noopener,noreferrer");
    return;
  }
  if (span.stepId) emit("focusStep", span.stepId);
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
    case "router":
      return Split;
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
    <!-- A grid, not per-row flex: the label and duration columns take their width
         from the widest row, so every track starts at the same x without padding the
         short labels out to a fixed width. -->
    <div class="grid grid-cols-[auto_auto_minmax(80px,1fr)] items-center gap-x-3 gap-y-1.5 text-sm">
      <template
        v-for="span in spans"
        :key="span.id"
      >
        <!-- No nesting indent: every row's icon starts at the same edge, which is
             what makes the column scannable top to bottom. -->
        <div class="flex min-w-0 max-w-[14rem] items-center gap-2 md:max-w-[24rem]">
          <component
            :is="iconComponent(span.icon)"
            class="w-4 h-4 shrink-0 text-muted-foreground"
          />
          <button
            v-if="isLinked(span)"
            type="button"
            class="min-w-0 truncate text-left text-muted-foreground hover:text-foreground hover:underline"
            :title="span.traceId ? 'Open this trace in a new tab' : 'Jump to this step'"
            :data-testid="`duration-span-link-${span.id}`"
            @click="activateSpan(span, $event)"
          >
            {{ span.label }}
          </button><span
            v-else
            class="min-w-0 truncate text-muted-foreground"
            :title="span.label"
          >
            {{ span.label }}
          </span>
        </div>
        <span class="text-right text-muted-foreground tabular-nums">
          {{ formatDuration(span.durationMs) }}
        </span>
        <div class="min-w-0">
          <div
            class="h-2 rounded bg-primary/20 overflow-hidden"
            role="presentation"
          >
            <div
              class="h-full rounded bg-primary transition-all"
              :style="{
                width: `${barWidthPercent(span)}%`,
                marginLeft: `${barOffsetPercent(span)}%`,
              }"
            />
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
