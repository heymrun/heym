<script setup lang="ts">
import { computed } from "vue";
import { FileSpreadsheet, MessageSquare, ShieldCheck, Table2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the question with a file · 1: the structure is inspected · 2: the answer.
const step = useCycleStep(3, 2400);

interface MockLine {
  id: string;
  from: "user" | "assistant";
  text: string;
  kind?: "file" | "inspect" | "result";
}

const question: MockLine = {
  id: "ask",
  from: "user",
  text: "Add the Summary sheet's total to the last page's value",
};

const lines = computed<MockLine[]>(() => {
  const attached: MockLine = { id: "file", from: "user", text: "q3-report.xlsx · 48 MB", kind: "file" };
  if (step.value === 0) {
    return [question, attached];
  }
  const inspected: MockLine = {
    id: "inspect",
    from: "assistant",
    text: "4 sheets · Summary: 12 columns, 1,204 rows",
    kind: "inspect",
  };
  if (step.value === 1) {
    return [question, attached, inspected];
  }
  return [
    question,
    attached,
    inspected,
    { id: "result", from: "assistant", text: "Total 1,284,310 + 96,420 = 1,380,730", kind: "result" },
  ];
});

const caption = computed<string>(
  () =>
    [
      "Attach a large file, it goes to Drive",
      "Chat inspects the structure in a sandbox",
      "Then reads only the cells it needs",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <MessageSquare class="h-3 w-3" />
      Chat · File analysis
      <span class="ml-auto flex items-center gap-1">
        <ShieldCheck class="h-3 w-3 text-emerald-500" />
        No network
      </span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1">
      <TransitionGroup
        enter-active-class="transition-all duration-500"
        enter-from-class="opacity-0 translate-y-1"
      >
        <div
          v-for="line in lines"
          :key="line.id"
          class="flex items-center gap-2 rounded-md border px-2.5 py-1 text-[11px] leading-4"
          :class="line.from === 'user'
            ? 'ml-6 border-primary/40 bg-primary/10'
            : line.kind === 'result'
              ? 'mr-6 border-emerald-500/40 bg-emerald-500/10'
              : 'mr-6 border-border bg-background'"
        >
          <FileSpreadsheet
            v-if="line.kind === 'file'"
            class="h-3 w-3 shrink-0 text-primary"
          />
          <Table2
            v-else-if="line.kind === 'inspect'"
            class="h-3 w-3 shrink-0 text-muted-foreground"
          />
          <span class="truncate text-foreground">{{ line.text }}</span>
        </div>
      </TransitionGroup>
    </div>

    <p class="shrink-0 text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
