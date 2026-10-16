<script setup lang="ts">
import { Wrench } from "lucide-vue-next";

import { formatTokenCount } from "@/lib/traceSpans";
import type { ToolTokenEstimate } from "@/types/trace";

defineProps<{
  estimate: ToolTokenEstimate;
  /** What clicking the row does, shown last because the native title is off here. */
  hint: string | null;
}>();
</script>

<template>
  <div class="min-w-[13rem] max-w-[17rem] space-y-2">
    <div class="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      <Wrench class="h-3.5 w-3.5" />
      Tool cost
    </div>
    <div class="flex items-baseline gap-1.5 tabular-nums">
      <span
        class="text-base font-semibold"
        data-testid="tool-token-cost"
      >
        ~{{ formatTokenCount(estimate.tokens) }}
      </span>
      <span class="text-muted-foreground">tokens</span>
    </div>
    <p class="whitespace-normal font-normal leading-snug text-muted-foreground">
      Turn {{ estimate.readByTurn }}'s prompt grew by this much once the result was added.
      <template v-if="estimate.sharedBy > 1">
        Shared with {{ estimate.sharedBy - 1 }} other tool{{ estimate.sharedBy === 2 ? "" : "s" }}
        in this step, split by result size.
      </template>
    </p>
    <div
      v-if="hint"
      class="text-[11px] text-muted-foreground"
    >
      {{ hint }}
    </div>
  </div>
</template>
