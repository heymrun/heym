<script setup lang="ts">
import { computed } from "vue";
import { CheckCircle2, Clock3, History } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

const step = useCycleStep(3, 1500);
const historyOpen = computed(() => step.value > 0);
const selectedRun = computed(() => step.value === 2);
</script>

<template>
  <div class="flex h-full w-full gap-2 p-3">
    <div class="flex min-w-0 flex-1 flex-col gap-1.5 rounded-lg border border-border bg-surface-sunken p-2">
      <div class="flex items-center justify-between gap-1">
        <span class="flex min-w-0 items-center gap-1 text-[10px] font-semibold text-foreground">
          <CheckCircle2 class="h-3 w-3 shrink-0 text-emerald-500" />
          <span class="truncate">Last Run Details</span>
        </span>
        <span
          class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-colors duration-300"
          :class="historyOpen ? 'bg-primary/15 text-primary' : 'text-muted-foreground'"
        >
          <History class="h-3 w-3" />
        </span>
      </div>
      <p class="text-[10px] font-medium text-foreground">
        Completed successfully in 1.2s
      </p>
      <p class="text-[9px] text-muted-foreground">
        cron · just now
      </p>
    </div>

    <Transition
      enter-active-class="transition-all duration-300"
      enter-from-class="translate-x-2 opacity-0"
      leave-active-class="transition-all duration-200"
      leave-to-class="translate-x-2 opacity-0"
    >
      <div
        v-if="historyOpen"
        class="flex w-[52%] flex-col gap-1 rounded-lg border border-primary/30 bg-card p-2"
      >
        <div class="flex items-center gap-1 text-[10px] font-semibold text-foreground">
          <Clock3 class="h-3 w-3 text-primary" />
          Run history
        </div>
        <div
          class="rounded border px-1.5 py-1 transition-colors duration-300"
          :class="selectedRun ? 'border-primary bg-primary/10' : 'border-border bg-muted/30'"
        >
          <p class="text-[9px] font-medium text-foreground">
            Today · success
          </p>
          <p class="text-[8px] text-muted-foreground">
            1.2s · cron
          </p>
        </div>
        <div class="rounded border border-border bg-muted/20 px-1.5 py-1 opacity-75">
          <p class="text-[9px] font-medium text-foreground">
            Yesterday · success
          </p>
          <p class="text-[8px] text-muted-foreground">
            0.9s · cron
          </p>
        </div>
      </div>
    </Transition>
  </div>
</template>
