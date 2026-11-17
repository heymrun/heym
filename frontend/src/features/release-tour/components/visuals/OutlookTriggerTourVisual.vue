<script setup lang="ts">
import { computed } from "vue";
import { Check, Flag, MailOpen, Play } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: an older email in the Focused Inbox gets flagged · 1: at the next poll
// the Outlook Trigger starts a run for it · 2: the after-run action marks it read.
const step = useCycleStep(3, 2400);

interface MockEmail {
  sender: string;
  subject: string;
  time: string;
}

const tabs = ["Focused", "Other"];
const flagged: MockEmail = { sender: "Mia Chen", subject: "Contract renewal terms", time: "Mon" };
const others: MockEmail[] = [
  { sender: "IT Desk", subject: "Laptop refresh schedule", time: "10:02" },
  { sender: "Finance", subject: "Q4 budget review", time: "9:15" },
  { sender: "Sam Lee", subject: "Re: kickoff agenda", time: "Tue" },
];

const running = computed<boolean>(() => step.value >= 1);
const done = computed<boolean>(() => step.value === 2);

const caption = computed<string>(
  () =>
    [
      "You flag an older email in the Focused Inbox",
      "At the next poll, Outlook Trigger starts a run",
      "Then marks it read",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-1.5 rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-end gap-3 border-b border-border text-[10px] leading-4">
      <span
        v-for="tab in tabs"
        :key="tab"
        class="relative pb-1"
        :class="tab === 'Focused' ? 'font-medium text-foreground' : 'text-muted-foreground'"
      >
        {{ tab }}
        <span
          v-if="tab === 'Focused'"
          class="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-[hsl(var(--node-outlook))]"
        />
      </span>
      <span class="ml-auto flex items-center gap-1 pb-1 text-muted-foreground">
        <Flag class="h-3 w-3" />
        Flagged email only
      </span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden">
      <div
        v-for="email in others.slice(0, 2)"
        :key="email.subject"
        class="flex shrink-0 items-center gap-1.5 rounded border border-border px-2 py-0.5 text-[11px] leading-4 text-muted-foreground"
      >
        <span class="w-14 shrink-0 truncate">{{ email.sender }}</span>
        <span class="min-w-0 flex-1 truncate">{{ email.subject }}</span>
        <span class="shrink-0 text-[10px]">{{ email.time }}</span>
      </div>
      <div
        class="flex shrink-0 items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] leading-4 transition-all duration-500"
        :class="running && !done ? 'border-[hsl(var(--node-outlook)/0.6)]' : 'border-border'"
      >
        <span
          class="w-14 shrink-0 truncate"
          :class="done ? 'text-muted-foreground' : 'font-medium text-foreground'"
        >{{ flagged.sender }}</span>
        <span
          class="min-w-0 flex-1 truncate"
          :class="done ? 'text-muted-foreground' : 'text-foreground'"
        >{{ flagged.subject }}</span>
        <Flag class="h-3 w-3 shrink-0 fill-destructive text-destructive" />
        <span class="shrink-0 text-[10px] text-muted-foreground">{{ flagged.time }}</span>
      </div>
      <div
        v-for="email in others.slice(2)"
        :key="email.subject"
        class="flex shrink-0 items-center gap-1.5 rounded border border-border px-2 py-0.5 text-[11px] leading-4 text-muted-foreground"
      >
        <span class="w-14 shrink-0 truncate">{{ email.sender }}</span>
        <span class="min-w-0 flex-1 truncate">{{ email.subject }}</span>
        <span class="shrink-0 text-[10px]">{{ email.time }}</span>
      </div>
    </div>

    <div
      class="flex shrink-0 items-center gap-1.5 rounded border border-dashed px-2 py-0.5 text-[11px] leading-4 transition-colors duration-500"
      :class="running ? 'border-[hsl(var(--node-outlook)/0.6)] text-foreground' : 'border-border text-muted-foreground'"
    >
      <MailOpen class="h-3 w-3 shrink-0 text-[hsl(var(--node-outlook))]" />
      <span class="min-w-0 truncate">Outlook Trigger</span>
      <span
        v-if="!running"
        class="ml-auto shrink-0 text-[10px] text-muted-foreground"
      >Watching Focused Inbox</span>
      <span
        v-else-if="!done"
        class="ml-auto flex shrink-0 items-center gap-1 text-[10px]"
      >
        <Play class="h-3 w-3 text-[hsl(var(--node-outlook))]" />
        Run started
      </span>
      <span
        v-else
        class="ml-auto flex shrink-0 items-center gap-1 text-[10px]"
      >
        <Check class="h-3 w-3 text-[hsl(var(--success))]" />
        Mark as read
      </span>
    </div>
    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
