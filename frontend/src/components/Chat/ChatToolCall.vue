<script setup lang="ts">
import { ref } from "vue";
import { Ban, Check, ChevronDown, ChevronRight, Loader2, TriangleAlert, Zap } from "lucide-vue-next";

import type { ToolCall } from "@/types/chat";

interface Props {
  toolCall: ToolCall;
}

defineProps<Props>();

const isOpen = ref(false);

function toggle(): void {
  isOpen.value = !isOpen.value;
}

function formatDuration(ms: number | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function prettyArgs(args: Record<string, unknown>): string {
  if (!args || Object.keys(args).length === 0) return "(no arguments)";
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}
</script>

<template>
  <div
    class="chat-tool-call rounded-lg border text-xs"
    :class="{
      'border-border/40 bg-muted/40': toolCall.status === 'running' || toolCall.status === 'success' || toolCall.status === 'cancelled',
      'border-destructive/40 bg-destructive/5': toolCall.status === 'error',
      'border-primary/30 bg-primary/5': toolCall.status === 'compressed',
    }"
  >
    <button
      type="button"
      class="w-full flex items-center gap-2 px-3 py-2 text-left text-muted-foreground hover:text-foreground transition-colors"
      @click="toggle"
    >
      <component
        :is="isOpen ? ChevronDown : ChevronRight"
        class="w-3.5 h-3.5 shrink-0"
      />
      <Loader2
        v-if="toolCall.status === 'running'"
        class="w-3.5 h-3.5 shrink-0 animate-spin text-primary"
      />
      <Check
        v-else-if="toolCall.status === 'success'"
        class="w-3.5 h-3.5 shrink-0 text-emerald-600 dark:text-emerald-400"
      />
      <TriangleAlert
        v-else-if="toolCall.status === 'error'"
        class="w-3.5 h-3.5 shrink-0 text-destructive"
      />
      <Ban
        v-else-if="toolCall.status === 'cancelled'"
        class="w-3.5 h-3.5 shrink-0 text-muted-foreground"
      />
      <Zap
        v-else
        class="w-3.5 h-3.5 shrink-0 text-primary"
      />
      <span class="flex-1 truncate">{{ toolCall.label }}</span>
      <span
        v-if="toolCall.elapsed_ms != null"
        class="text-[10px] opacity-70 tabular-nums shrink-0"
      >{{ formatDuration(toolCall.elapsed_ms) }}</span>
    </button>
    <div
      v-if="isOpen"
      class="border-t border-border/30 px-3 py-2 space-y-2"
    >
      <div>
        <p class="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1">
          Arguments
        </p>
        <pre class="max-h-64 overflow-auto rounded bg-background/60 p-2 text-[11px] leading-snug">{{ prettyArgs(toolCall.args) }}</pre>
      </div>
      <div v-if="toolCall.response_summary">
        <p class="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1">
          Result
        </p>
        <p class="text-[11px] whitespace-pre-wrap break-words text-foreground/80">
          {{ toolCall.response_summary }}
        </p>
      </div>
    </div>
  </div>
</template>
