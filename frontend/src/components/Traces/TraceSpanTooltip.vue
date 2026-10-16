<script setup lang="ts">
import TraceTokenUsage from "@/components/Traces/TraceTokenUsage.vue";
import TraceToolTokenCost from "@/components/Traces/TraceToolTokenCost.vue";
import Tooltip from "@/components/ui/Tooltip.vue";
import { hasTokenTooltip } from "@/lib/traceSpans";
import type { TraceSpan } from "@/types/trace";

defineProps<{
  span: TraceSpan;
  /** What clicking the trigger does, or null where the trigger is not clickable. */
  hint: string | null;
  /** For the line, which spans the track: the card opens at the pointer, not mid-line. */
  followPointer?: boolean;
}>();
</script>

<template>
  <!-- The card is only read, so the pointer passes through it: leaving the trigger or
       scrolling closes it, and a wheel over it still moves the panel underneath. -->
  <Tooltip
    label="Token usage"
    :disabled="!hasTokenTooltip(span)"
    side="top"
    :interactive="false"
    :follow-pointer="followPointer"
    content-class="px-3 py-2.5 shadow-lg"
  >
    <slot />
    <template #content>
      <TraceToolTokenCost
        v-if="span.toolTokens"
        :estimate="span.toolTokens"
        :hint="hint"
      />
      <TraceTokenUsage
        v-else
        :span="span"
        :hint="hint"
      />
    </template>
  </Tooltip>
</template>
