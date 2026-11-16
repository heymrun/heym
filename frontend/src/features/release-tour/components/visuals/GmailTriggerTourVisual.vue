<script setup lang="ts">
import { computed } from "vue";
import { Archive, Check, Mails, Play, Tag } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: a new email lands in the Primary tab, sent to an alias · 1: the Gmail
// Trigger starts a run · 2: the after-run action marks it read and archives it.
const step = useCycleStep(3, 2400);

interface MockEmail {
  sender: string;
  subject: string;
  time: string;
}

const tabs = ["Primary", "Promotions", "Updates"];
const incoming: MockEmail = { sender: "Ana Ruiz", subject: "Quote request for 40 seats", time: "now" };
const earlier: MockEmail[] = [
  { sender: "Billing", subject: "Invoice INV-2041", time: "9:12" },
  { sender: "Team", subject: "Weekly team notes", time: "8:40" },
  { sender: "Jon Park", subject: "Re: onboarding call", time: "Mon" },
];

const running = computed<boolean>(() => step.value >= 1);
const done = computed<boolean>(() => step.value === 2);

const caption = computed<string>(
  () =>
    [
      "A new email reaches the Primary tab, sent to sales@",
      "Gmail Trigger starts a run for it",
      "Then marks it read and archives it",
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
        :class="tab === 'Primary' ? 'font-medium text-foreground' : 'text-muted-foreground'"
      >
        {{ tab }}
        <span
          v-if="tab === 'Primary'"
          class="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-[hsl(var(--node-gmail))]"
        />
      </span>
      <span class="ml-auto flex items-center gap-1 pb-1 text-muted-foreground">
        <Tag class="h-3 w-3" />
        sales@example.com
      </span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden">
      <div
        class="flex shrink-0 items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] leading-4 transition-all duration-500"
        :class="[
          running && !done ? 'border-[hsl(var(--node-gmail)/0.6)]' : 'border-border',
          done ? 'opacity-40' : 'opacity-100',
        ]"
      >
        <span
          class="h-1.5 w-1.5 shrink-0 rounded-full bg-[hsl(var(--node-gmail))] transition-opacity duration-500"
          :class="done ? 'opacity-0' : 'opacity-100'"
        />
        <span
          class="w-14 shrink-0 truncate"
          :class="done ? 'text-muted-foreground' : 'font-medium text-foreground'"
        >{{ incoming.sender }}</span>
        <span
          class="min-w-0 flex-1 truncate"
          :class="done ? 'text-muted-foreground' : 'text-foreground'"
        >{{ incoming.subject }}</span>
        <Archive
          v-if="done"
          class="h-3 w-3 shrink-0 text-muted-foreground"
        />
        <span
          v-else
          class="shrink-0 text-[10px] text-muted-foreground"
        >{{ incoming.time }}</span>
      </div>
      <div
        v-for="email in earlier"
        :key="email.subject"
        class="flex shrink-0 items-center gap-1.5 rounded border border-border px-2 py-0.5 text-[11px] leading-4 text-muted-foreground"
      >
        <span class="h-1.5 w-1.5 shrink-0" />
        <span class="w-14 shrink-0 truncate">{{ email.sender }}</span>
        <span class="min-w-0 flex-1 truncate">{{ email.subject }}</span>
        <span class="shrink-0 text-[10px]">{{ email.time }}</span>
      </div>
    </div>

    <div
      class="flex shrink-0 items-center gap-1.5 rounded border border-dashed px-2 py-0.5 text-[11px] leading-4 transition-colors duration-500"
      :class="running ? 'border-[hsl(var(--node-gmail)/0.6)] text-foreground' : 'border-border text-muted-foreground'"
    >
      <Mails class="h-3 w-3 shrink-0 text-[hsl(var(--node-gmail))]" />
      <span class="min-w-0 truncate">Gmail Trigger</span>
      <span
        v-if="!running"
        class="ml-auto shrink-0 text-[10px] text-muted-foreground"
      >Watching Primary</span>
      <span
        v-else-if="!done"
        class="ml-auto flex shrink-0 items-center gap-1 text-[10px]"
      >
        <Play class="h-3 w-3 text-[hsl(var(--node-gmail))]" />
        Run started
      </span>
      <span
        v-else
        class="ml-auto flex shrink-0 items-center gap-1 text-[10px]"
      >
        <Check class="h-3 w-3 text-[hsl(var(--success))]" />
        Mark as read and archive
      </span>
    </div>
    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
