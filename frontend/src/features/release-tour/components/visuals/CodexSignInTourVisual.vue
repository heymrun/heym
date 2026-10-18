<script setup lang="ts">
import { computed } from "vue";
import { Check, Copy, Loader2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: sign in · 1: the code is shown and copied · 2: waiting for OpenAI · 3: connected.
const step = useCycleStep(4, 1600);

const caption = computed<string>(() => {
  if (step.value === 0) return "Click Sign in with ChatGPT";
  if (step.value === 1) return "Heym copies a short code";
  if (step.value === 2) return "Enter it on OpenAI and approve";
  return "Heym finishes by itself";
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-3 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      OpenAI Codex credential
      <span class="ml-auto rounded bg-muted px-1.5 text-[10px] leading-4">ChatGPT</span>
    </div>

    <div
      class="rounded-md border px-2.5 py-2 text-center text-[11px] leading-4 transition-colors duration-500"
      :class="step === 0 ? 'border-primary/60 bg-primary/10 text-foreground' : 'border-border bg-background text-muted-foreground'"
    >
      Sign in with ChatGPT
    </div>

    <div
      class="space-y-2 rounded-md border px-2.5 py-2.5 transition-opacity duration-500"
      :class="step === 1 || step === 2 ? 'border-border bg-muted/40 opacity-100' : 'border-transparent opacity-30'"
    >
      <div class="flex items-center justify-center gap-2">
        <span class="font-mono text-base font-semibold tracking-[0.2em] text-foreground">K7QX-4MPD</span>
        <Check
          v-if="step >= 1"
          class="h-3.5 w-3.5 text-primary"
        />
        <Copy
          v-else
          class="h-3.5 w-3.5 text-muted-foreground"
        />
      </div>
      <p class="flex items-center justify-center gap-1.5 text-[10px] leading-4 text-muted-foreground">
        <Loader2
          class="h-3 w-3"
          :class="step === 2 ? 'animate-spin' : ''"
        />
        Waiting for you to approve on OpenAI
      </p>
    </div>

    <div class="mt-auto flex items-center justify-between text-[10px] leading-4">
      <span class="text-muted-foreground">{{ caption }}</span>
      <span
        class="flex items-center gap-1 rounded-md px-2 py-1 transition-colors duration-500"
        :class="step === 3 ? 'bg-primary/15 text-primary' : 'text-muted-foreground'"
      >
        <Check class="h-3 w-3" />
        Connected
      </span>
    </div>
  </div>
</template>
