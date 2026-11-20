<script setup lang="ts">
import { computed } from "vue";
import { Loader2, Sparkles, Trash2 } from "lucide-vue-next";

import { aiInsertTooltip, clearAllTooltip } from "@/components/Dialogs/agentMemoryBulkActions";
import Tooltip from "@/components/ui/Tooltip.vue";

interface Props {
  /** The agent's model, or null when the agent has none selected. */
  model: string | null;
  insertOpen: boolean;
  inserting: boolean;
  clearing: boolean;
  /** Loading or any other write in flight: both buttons wait for it. */
  busy: boolean;
  entityCount: number;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "toggle-insert"): void;
  (e: "clear"): void;
}>();

const insertDisabled = computed<boolean>(
  () => !props.model || props.busy || props.inserting || props.clearing,
);
const clearDisabled = computed<boolean>(
  () => props.entityCount === 0 || props.busy || props.inserting || props.clearing,
);
</script>

<template>
  <!-- Each button sits in a span: a disabled button gets no pointer events, so the span is what
       the tooltip listens on, and the reason it is disabled still shows on hover. -->
  <Tooltip :label="aiInsertTooltip(model)">
    <span class="mr-1 inline-flex">
      <button
        type="button"
        class="agent-memory-ai-insert flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium text-primary transition-all duration-200 dark:text-brand-primary-soft disabled:pointer-events-none disabled:opacity-40 disabled:shadow-none"
        :class="insertOpen ? 'border-primary bg-primary/10' : 'border-primary/50 hover:bg-primary/10'"
        :disabled="insertDisabled"
        :aria-pressed="insertOpen"
        aria-label="AI insert from text"
        data-testid="agent-memory-ai-insert"
        @click="emit('toggle-insert')"
      >
        <Loader2
          v-if="inserting"
          class="h-3.5 w-3.5 animate-spin"
        />
        <Sparkles
          v-else
          class="h-3.5 w-3.5"
        />
        <span class="hidden sm:inline">AI insert</span>
      </button>
    </span>
  </Tooltip>
  <Tooltip :label="clearAllTooltip(entityCount)">
    <span class="inline-flex">
      <button
        type="button"
        class="agent-memory-clear-all flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-all duration-200 hover:text-destructive disabled:pointer-events-none disabled:opacity-40"
        :disabled="clearDisabled"
        aria-label="Clear all memory"
        data-testid="agent-memory-clear-all"
        @click="emit('clear')"
      >
        <Loader2
          v-if="clearing"
          class="h-3.5 w-3.5 animate-spin"
        />
        <Trash2
          v-else
          class="h-3.5 w-3.5"
        />
      </button>
    </span>
  </Tooltip>
</template>

<style scoped>
.agent-memory-ai-insert:not(:disabled) {
  box-shadow: 0 0 12px hsl(var(--primary) / 0.35);
}
.agent-memory-clear-all {
  background: hsl(var(--muted) / 0.5);
}
.agent-memory-clear-all:hover:not(:disabled) {
  background: hsl(var(--destructive) / 0.1);
}
</style>
