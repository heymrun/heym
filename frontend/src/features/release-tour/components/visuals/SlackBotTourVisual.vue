<script setup lang="ts">
import { computed } from "vue";
import { CircleCheck, CornerDownRight, Hash, PauseCircle } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the approval is posted and the run waits · 1: someone presses Approve ·
// 2: the buttons turn into who approved · 3: the outcome lands in the same thread.
const step = useCycleStep(4, 1600);

const pressed = computed<boolean>(() => step.value === 1);
const answered = computed<boolean>(() => step.value >= 2);
const outcome = computed<boolean>(() => step.value === 3);

const caption = computed<string>(() => {
  if (step.value === 0) return "Run paused: waiting for an answer in Slack";
  if (step.value === 1) return "Ana presses Approve";
  if (step.value === 2) return "The run continues with approval = approved";
  return "Post final outcome replies in the thread";
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-1 text-[11px] leading-none text-muted-foreground">
      <Hash class="h-3.5 w-3.5" />finance-approvals
      <span
        class="ml-auto flex items-center gap-1 rounded-full px-2 py-1 transition-colors duration-500"
        :class="answered ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-primary/10 text-primary'"
      >
        <PauseCircle
          v-if="!answered"
          class="h-3 w-3"
        />
        <CircleCheck
          v-else
          class="h-3 w-3"
        />
        {{ answered ? "resumed" : "waiting" }}
      </span>
    </div>

    <div class="flex gap-2.5 rounded-md border border-border/60 bg-background p-2.5">
      <img
        src="/fav.svg"
        alt=""
        class="h-6 w-6 shrink-0"
      >
      <div class="min-w-0 flex-1">
        <p class="text-[11px] font-semibold leading-tight text-foreground">
          Heym
        </p>
        <p class="mt-1 text-[11px] leading-tight text-muted-foreground">
          Refund of $420 for Acme Ltd?
        </p>
        <div class="mt-2 flex h-5 items-center gap-1.5">
          <template v-if="!answered">
            <span
              class="rounded border px-2 py-1 text-[9px] leading-none transition-all duration-300"
              :class="pressed ? 'scale-95 border-[hsl(var(--success))] bg-[hsl(var(--success))] text-[hsl(var(--success-foreground))]' : 'border-[hsl(var(--success)/0.6)] text-[hsl(var(--success))]'"
            >Approve</span>
            <span class="rounded border border-border/60 px-2 py-1 text-[9px] leading-none text-muted-foreground">Request changes</span>
            <span class="rounded border border-destructive/60 px-2 py-1 text-[9px] leading-none text-destructive">Reject</span>
          </template>
          <span
            v-else
            class="flex items-center gap-1 text-[10px] leading-none text-[hsl(var(--success))]"
          >
            <CircleCheck class="h-3 w-3" />Approved by @ana
          </span>
        </div>
      </div>
    </div>

    <div
      class="ml-4 flex items-center gap-2 transition-all duration-500"
      :class="outcome ? 'translate-y-0 opacity-100' : 'translate-y-1 opacity-0'"
    >
      <CornerDownRight class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span class="flex flex-1 items-center gap-2 rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-[11px] leading-none text-foreground">
        <span class="h-2 w-2 shrink-0 rounded-full bg-[hsl(var(--success))]" />
        Refund approved
        <span class="ml-auto text-[9px] text-muted-foreground">in thread</span>
      </span>
    </div>

    <p class="mt-auto truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
