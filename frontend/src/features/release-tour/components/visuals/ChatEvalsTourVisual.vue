<script setup lang="ts">
import { computed } from "vue";
import { CheckCircle2, MessageSquare, XCircle } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the request · 1: the credential question · 2: the run reported back.
const step = useCycleStep(3, 2400);

interface MockLine {
  id: string;
  from: "user" | "assistant";
  text: string;
  state?: "pass" | "fail";
}

const request: MockLine = {
  id: "ask",
  from: "user",
  text: "Make a prompt suite for my support prompt and compare two models",
};

const lines = computed<MockLine[]>(() => {
  if (step.value === 0) {
    return [request, { id: "wrote", from: "assistant", text: "Wrote 5 test cases with expected answers" }];
  }
  if (step.value === 1) {
    return [request, { id: "which", from: "assistant", text: "Which credential? OpenAI · Work, or Gemini" }];
  }
  return [
    request,
    { id: "m1", from: "assistant", text: "gpt-4o · 5/5 passed", state: "pass" },
    { id: "m2", from: "assistant", text: "gpt-4.1-mini · 4/5 passed", state: "fail" },
  ];
});

const caption = computed<string>(
  () =>
    [
      "Chat writes the test cases",
      "It asks which credential to use",
      "Then runs the suite and reports back",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <MessageSquare class="h-3 w-3" />
      Chat · Evals
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1.5">
      <div
        v-for="line in lines"
        :key="line.id"
        class="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 transition-colors duration-500"
        :class="line.from === 'user'
          ? 'ml-6 border-primary/40 bg-primary/10'
          : line.state === 'fail'
            ? 'mr-6 border-destructive/40 bg-destructive/10'
            : 'mr-6 border-border bg-background'"
      >
        <CheckCircle2
          v-if="line.state === 'pass'"
          class="h-3 w-3 shrink-0 text-emerald-500"
        />
        <XCircle
          v-else-if="line.state === 'fail'"
          class="h-3 w-3 shrink-0 text-destructive"
        />
        <span class="truncate text-foreground">{{ line.text }}</span>
      </div>
    </div>

    <p class="text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
