<script setup lang="ts">
import { computed } from "vue";
import { CircleCheck, Hash, MessageSquareReply, PauseCircle } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the approval is posted and the run waits · 1: someone presses Approve ·
// 2: the buttons turn into who approved · 3: the outcome lands in the same thread.
const step = useCycleStep(4, 1500);

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
  <div class="flex h-full w-full flex-col justify-between gap-2 rounded-lg bg-card p-3">
    <div class="flex items-center gap-1 text-[10px] leading-none text-muted-foreground">
      <Hash class="h-3 w-3" />finance-approvals
      <span
        class="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors duration-500"
        :class="answered ? 'bg-success/15 text-success' : 'bg-primary/10 text-primary'"
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

    <div class="rounded-md border border-border/60 bg-background p-2">
      <p class="text-[10px] font-semibold leading-tight text-foreground">
        Heym
      </p>
      <p class="mt-0.5 text-[10px] leading-tight text-muted-foreground">
        Refund of $420 for Acme Ltd?
      </p>
      <div
        v-if="!answered"
        class="mt-1.5 flex gap-1"
      >
        <span
          class="rounded border px-1.5 py-0.5 text-[9px] leading-none transition-all duration-300"
          :class="pressed ? 'scale-95 border-success bg-success text-success-foreground' : 'border-success/60 text-success'"
        >Approve</span>
        <span class="rounded border border-border/60 px-1.5 py-0.5 text-[9px] leading-none text-muted-foreground">Request changes</span>
        <span class="rounded border border-destructive/60 px-1.5 py-0.5 text-[9px] leading-none text-destructive">Reject</span>
      </div>
      <p
        v-else
        class="mt-1.5 text-[9px] leading-none text-muted-foreground"
      >
        Approved by @ana
      </p>
    </div>

    <div
      class="flex items-center gap-1.5 rounded-md border-l-2 border-success bg-background px-2 py-1 text-[10px] leading-none transition-opacity duration-500"
      :class="outcome ? 'opacity-100' : 'opacity-0'"
    >
      <MessageSquareReply class="h-3 w-3 text-muted-foreground" />
      <span class="text-foreground">Refund approved</span>
    </div>

    <p class="truncate text-[10px] leading-none text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
