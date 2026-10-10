<script setup lang="ts">
import { computed } from "vue";
import { FileArchive, Sparkles } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: a zip is attached · 1: Chat reads SKILL.md · 2: the agent has the skill.
const step = useCycleStep(3, 1600);

const caption = computed<string>(() => {
  if (step.value === 0) return "Drop a skill zip in Chat";
  if (step.value === 1) return "Chat reads SKILL.md";
  return "The agent keeps the skill";
});
</script>

<template>
  <div class="flex h-full w-full flex-col justify-between rounded-lg bg-card p-3">
    <div class="flex items-center gap-2 text-[10px] text-muted-foreground">
      <FileArchive class="h-3.5 w-3.5" />
      invoice-helper.zip
    </div>
    <div
      class="rounded-md border px-2 py-2 text-[10px] leading-snug transition-colors duration-500"
      :class="step > 0 ? 'border-primary/60 bg-primary/10 text-foreground' : 'border-border bg-background text-muted-foreground'"
    >
      <p class="font-medium">
        SKILL.md
      </p>
      <p class="mt-1">
        Read the invoice and list the line items.
      </p>
    </div>
    <div class="flex items-center justify-between text-[10px]">
      <span class="text-muted-foreground">{{ caption }}</span>
      <span
        class="flex items-center gap-1 rounded-md px-2 py-1 transition-colors duration-500"
        :class="step === 2 ? 'bg-primary/15 text-primary' : 'text-muted-foreground'"
      >
        <Sparkles class="h-3 w-3" />
        Agent
      </span>
    </div>
  </div>
</template>
