<script setup lang="ts">
import { computed } from "vue";
import { CheckCircle2, Loader2, Network } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: A2A off · 1: A2A on, the card URL appears · 2: a task works · 3: it completes.
const step = useCycleStep(4, 1700);

const enabled = computed<boolean>(() => step.value >= 1);

const taskState = computed<string>(() => {
  if (step.value < 2) return "";
  return step.value === 2 ? "TASK_STATE_WORKING" : "TASK_STATE_COMPLETED";
});

const caption = computed<string>(() => {
  if (step.value === 0) return "The Heym Agent answers MCP clients as heym_chat";
  if (step.value === 1) return "Enable A2A: other agents find it by its Agent Card";
  if (step.value === 2) return "An agent sends a task; progress streams back";
  return "The task completes with the reply and its links";
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      Heym Agent
      <span class="ml-auto rounded border border-primary/50 bg-primary/25 px-1.5 text-[10px] font-medium leading-4 text-foreground">
        {{ enabled ? "MCP · A2A" : "MCP" }}
      </span>
    </div>

    <!-- Every row keeps its slot and fades in, so the rows fill the stage at each step. -->
    <div class="flex min-h-0 flex-1 flex-col gap-2.5">
      <div class="flex flex-1 items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-[11px] leading-4">
        <span
          class="flex h-3.5 w-3.5 items-center justify-center rounded-sm border transition-colors duration-500"
          :class="enabled ? 'border-primary bg-primary text-primary-foreground' : 'border-border'"
        >
          <span
            v-if="enabled"
            class="text-[9px] leading-none"
          >✓</span>
        </span>
        <Network class="h-3 w-3 text-primary" />
        <span class="text-foreground">Enable A2A</span>
      </div>

      <div
        class="flex flex-1 items-center rounded-md bg-muted/50 px-2.5 py-1.5 font-mono text-[10px] leading-4 text-muted-foreground transition-opacity duration-500"
        :class="enabled ? 'opacity-100' : 'opacity-0'"
      >
        <span class="truncate">/.well-known/agent-card.json</span>
      </div>

      <div
        class="flex flex-1 items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 transition-all duration-500"
        :class="[
          taskState ? 'opacity-100' : 'opacity-0',
          step === 2 ? 'border-primary/50 bg-primary/10' : 'border-border bg-background',
        ]"
      >
        <Loader2
          v-if="step === 2"
          class="h-3 w-3 animate-spin text-primary"
        />
        <CheckCircle2
          v-else
          class="h-3 w-3 text-emerald-500"
        />
        <span class="text-foreground">SendMessage</span>
        <span class="ml-auto font-mono text-[10px] text-muted-foreground">{{ taskState }}</span>
      </div>
    </div>

    <p class="text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
