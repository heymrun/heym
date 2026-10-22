<script setup lang="ts">
import { computed } from "vue";
import { CircleCheck, GitBranch, MessageSquare, Send, Sparkles, Wand2, Wrench } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: AI on a node · 1: the assistant opens on that node ·
// 2: "Change this node as ..." is filled in · 3: only that node is updated.
const step = useCycleStep(4, 1700);

const panelOpen = computed<boolean>(() => step.value >= 1);
const typing = computed<boolean>(() => step.value === 2);
const updated = computed<boolean>(() => step.value === 3);

const caption = computed<string>(() => {
  if (step.value === 0) return "Click AI above a node";
  if (step.value === 1) return "The assistant opens on that node";
  if (step.value === 2) return "Say what should change";
  return "Only this node changes";
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 overflow-hidden rounded-lg bg-card p-3">
    <div class="flex min-h-0 flex-1 gap-2.5">
      <div class="flex w-[34%] shrink-0 items-center justify-center rounded-md bg-background/60">
        <div class="relative pt-6">
          <span
            class="absolute left-1/2 top-0 flex -translate-x-1/2 items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[9px] leading-none transition-all duration-500"
            :class="step === 0 ? 'scale-110 border-primary bg-primary/15 text-primary shadow-[0_0_10px_hsl(var(--primary)/0.45)]' : 'border-primary/50 text-primary'"
          >
            <Sparkles class="h-2.5 w-2.5" />AI
          </span>
          <div
            class="flex items-center gap-1 rounded-lg border px-1.5 py-1.5 transition-all duration-500"
            :class="updated ? 'border-[hsl(var(--success))] ring-2 ring-[hsl(var(--success)/0.4)]' : 'border-node-condition/60'"
          >
            <GitBranch class="h-3 w-3 shrink-0 text-node-condition" />
            <span class="text-[9px] leading-none">checkLinkedIn</span>
          </div>
        </div>
      </div>

      <div
        class="flex min-w-0 flex-1 flex-col gap-1 rounded-md border border-border bg-background p-1.5 transition-opacity duration-500"
        :class="panelOpen ? 'opacity-100' : 'opacity-30'"
      >
        <div class="flex items-center gap-1 text-[10px] leading-none text-muted-foreground">
          <Sparkles class="h-3 w-3 shrink-0 text-primary" />AI Assistant
        </div>
        <div class="flex min-w-0 items-center gap-1.5 rounded border border-border/70 bg-muted/40 px-1.5 py-1">
          <span class="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-node-condition/15">
            <GitBranch class="h-2.5 w-2.5 text-node-condition" />
          </span>
          <span class="truncate text-[10px] font-medium leading-snug">Modifying: checkLinkedIn</span>
        </div>
        <div class="flex min-h-0 flex-1 flex-col justify-end gap-1">
          <template v-if="!typing && !updated">
            <span
              class="flex min-w-0 items-center gap-1 rounded border px-1 py-0.5 text-[8px] leading-tight transition-colors duration-500"
              :class="step === 1 ? 'border-primary/60 bg-primary/10' : 'border-border'"
            ><Wand2 class="h-2.5 w-2.5 shrink-0 text-primary" /><span class="truncate">Change this node as ...</span></span>
            <span class="flex min-w-0 items-center gap-1 rounded border border-border px-1 py-0.5 text-[8px] leading-tight">
              <Wrench class="h-2.5 w-2.5 shrink-0 text-primary" /><span class="truncate">Fix error in this node ...</span>
            </span>
            <span class="flex min-w-0 items-center gap-1 rounded border border-border px-1 py-0.5 text-[8px] leading-tight">
              <MessageSquare class="h-2.5 w-2.5 shrink-0 text-primary" /><span class="truncate">Other</span>
            </span>
          </template>
          <p
            v-else-if="typing"
            class="line-clamp-3 rounded border border-primary/50 px-1 py-0.5 text-[8px] leading-tight"
          >
            Change this node to check follower engagement from the past 7 days
          </p>
          <p
            v-else
            class="flex min-w-0 items-center gap-1 rounded bg-[hsl(var(--success)/0.12)] px-1 py-0.5 text-[8px] leading-tight text-[hsl(var(--success))]"
          >
            <CircleCheck class="h-2.5 w-2.5 shrink-0" /><span class="truncate">checkLinkedIn updated</span>
          </p>
        </div>
        <span
          class="flex items-center justify-center gap-1 rounded px-1 py-0.5 text-[8px] leading-tight transition-colors duration-500"
          :class="typing ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'"
        ><Send class="h-2.5 w-2.5" />Send</span>
      </div>
    </div>

    <p class="shrink-0 text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
