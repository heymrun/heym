<script setup lang="ts">
import { computed } from "vue";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Bot,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Settings,
  User,
  Wrench,
} from "lucide-vue-next";

import type { TraceStep } from "@/lib/traceSteps";

import CopyButton from "@/components/Traces/CopyButton.vue";
import TraceJsonContent from "@/components/Traces/TraceJsonContent.vue";
import { renderMarkdown } from "@/lib/markdown";
import { getTraceJsonContent, isTraceJsonContent } from "@/lib/traceJson";

const props = defineProps<{
  step: TraceStep;
  open: boolean;
}>();

const emit = defineEmits<{
  (e: "toggle"): void;
}>();

const ICONS = {
  system: Settings,
  user: User,
  assistant: Bot,
  tool: Wrench,
  answer: CircleCheck,
  request: ArrowUpRight,
  response: ArrowDownLeft,
} as const;

const iconComponent = computed(() => ICONS[props.step.icon]);

function formatStepDuration(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

const jsonText = computed(() => getTraceJsonContent(props.step.json).rawText);
</script>

<template>
  <div
    class="rounded-lg border bg-muted/20 transition-colors"
    :class="open ? 'border-primary/40' : 'border-border/50'"
    :data-testid="`trace-step-${step.id}`"
  >
    <button
      type="button"
      class="flex w-full items-center gap-2 px-3 py-2 text-left"
      @click="emit('toggle')"
    >
      <span
        class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted"
        :class="step.isError ? 'text-destructive' : 'text-muted-foreground'"
      >
        <component
          :is="iconComponent"
          class="h-3.5 w-3.5"
        />
      </span>
      <span class="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {{ step.roleLabel }}
      </span>
      <span
        class="min-w-0 flex-1 truncate text-sm"
        :class="step.isError ? 'text-destructive' : ''"
      >
        {{ step.summary }}
      </span>
      <span
        v-for="(badge, i) in step.badges"
        :key="i"
        class="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary dark:bg-primary/25 dark:text-accent-foreground"
      >
        {{ badge.label }}
      </span>
      <span
        v-if="step.tokens != null"
        class="shrink-0 text-[11px] text-muted-foreground tabular-nums"
      >
        {{ step.tokens }} tok
      </span>
      <span
        v-if="step.durationMs != null"
        class="shrink-0 text-[11px] text-muted-foreground tabular-nums"
      >
        {{ formatStepDuration(step.durationMs) }}
      </span>
      <component
        :is="open ? ChevronDown : ChevronRight"
        class="h-4 w-4 shrink-0 text-muted-foreground"
      />
    </button>

    <div
      v-if="open"
      class="border-t border-border/40 px-3 py-3 space-y-3"
    >
      <template v-if="step.kind === 'tool'">
        <div
          v-if="step.argumentsText"
        >
          <TraceJsonContent
            :value="step.argumentsText"
            max-height="small"
          >
            <template #title>
              <span class="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Arguments
              </span>
            </template>
            <template #actions>
              <CopyButton :text="step.argumentsText" />
            </template>
          </TraceJsonContent>
        </div>
        <div
          v-if="step.resultText"
        >
          <TraceJsonContent
            :value="step.resultText"
            max-height="small"
          >
            <template #title>
              <span class="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Result
              </span>
            </template>
            <template #actions>
              <CopyButton :text="step.resultText" />
            </template>
          </TraceJsonContent>
        </div>
      </template>

      <TraceJsonContent
        v-else-if="step.detail && isTraceJsonContent(step.detail)"
        :value="step.detail"
      >
        <template #actions>
          <CopyButton :text="step.detail" />
        </template>
      </TraceJsonContent>

      <div
        v-else-if="step.detail && step.detailIsMarkdown"
        class="relative"
      >
        <CopyButton
          :text="step.detail"
          class="absolute right-1.5 top-1.5 z-[1]"
        />
        <!-- eslint-disable vue/no-v-html -->
        <div
          class="text-sm leading-relaxed break-words pr-10 [&_table]:w-full [&_table]:text-xs [&_td]:border [&_td]:border-border/40 [&_td]:px-1.5 [&_td]:py-0.5 [&_th]:px-1.5 [&_th]:py-0.5 [&_a]:text-primary [&_a]:underline [&_pre]:bg-muted/40 [&_pre]:p-2 [&_pre]:rounded [&_pre]:overflow-auto"
          v-html="renderMarkdown(step.detail)"
        />
        <!-- eslint-enable vue/no-v-html -->
      </div>

      <div
        v-else-if="step.detail"
        class="relative"
      >
        <CopyButton
          :text="step.detail"
          class="absolute right-1.5 top-1.5 z-[1]"
        />
        <div class="text-sm whitespace-pre-wrap break-words pr-10">
          {{ step.detail }}
        </div>
      </div>

      <TraceJsonContent :value="step.json">
        <template #title>
          <span class="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Event JSON
          </span>
        </template>
        <template #actions>
          <CopyButton :text="jsonText" />
        </template>
      </TraceJsonContent>
    </div>
  </div>
</template>
