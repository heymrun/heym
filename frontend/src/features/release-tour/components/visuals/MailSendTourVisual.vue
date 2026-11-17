<script setup lang="ts">
import { computed } from "vue";
import { Check, Paperclip, SendHorizontal } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: Gmail Send filled in, From set to an alias · 1: the email is sent and lands in
// Sent · 2: the same fields on Outlook Send · 3: sent from the Microsoft 365 mailbox.
const step = useCycleStep(4, 2200);

interface MockSender {
  name: string;
  color: string;
  from: string;
  aliases: string[];
  sentFolder: string;
}

const senders: MockSender[] = [
  {
    name: "Gmail Send",
    color: "--node-gmail",
    from: "support@example.com",
    aliases: ["team@example.com", "support@example.com"],
    sentFolder: "Sent",
  },
  {
    name: "Outlook Send",
    color: "--node-outlook",
    from: "sales@contoso.com",
    aliases: ["team@contoso.com", "sales@contoso.com"],
    sentFolder: "Sent Items",
  },
];

const sender = computed<MockSender>(() => senders[step.value < 2 ? 0 : 1]);
const sent = computed<boolean>(() => step.value % 2 === 1);
const fields = [
  { label: "To", value: "$trigger.email.fromAddresses[0].email" },
  { label: "Subject", value: "Re: $trigger.email.subject" },
  { label: "Body", value: "<p>$agent.text</p>" },
];

const caption = computed<string>(() =>
  sent.value
    ? `Sent from ${sender.value.from}, saved in ${sender.value.sentFolder}`
    : `${sender.value.name} has every Send Email field, plus From`,
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-1.5 rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-center gap-1.5 border-b border-border pb-1 text-[11px] leading-4">
      <SendHorizontal
        class="h-3.5 w-3.5 shrink-0 transition-colors duration-500"
        :style="{ color: `hsl(var(${sender.color}))` }"
      />
      <Transition
        mode="out-in"
        enter-from-class="opacity-0"
        leave-to-class="opacity-0"
        enter-active-class="transition-opacity duration-300"
        leave-active-class="transition-opacity duration-300"
      >
        <span
          :key="sender.name"
          class="font-medium text-foreground"
        >{{ sender.name }}</span>
      </Transition>
      <span class="ml-auto text-[10px] text-muted-foreground">No SMTP password</span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden">
      <div class="flex shrink-0 flex-col gap-0.5">
        <span class="text-[10px] leading-3 text-muted-foreground">From</span>
        <div class="flex flex-wrap gap-1">
          <span
            v-for="alias in sender.aliases"
            :key="alias"
            class="rounded-full border px-1.5 text-[10px] leading-4 transition-colors duration-500"
            :class="alias === sender.from ? 'text-foreground' : 'border-border text-muted-foreground'"
            :style="alias === sender.from ? { borderColor: `hsl(var(${sender.color}) / 0.6)` } : {}"
          >{{ alias }}</span>
        </div>
      </div>
      <div
        v-for="field in fields"
        :key="field.label"
        class="flex shrink-0 items-center gap-1.5 rounded border border-border px-2 py-0.5 text-[11px] leading-4"
      >
        <span class="w-11 shrink-0 text-muted-foreground">{{ field.label }}</span>
        <span class="min-w-0 flex-1 truncate font-mono text-[10px] text-foreground">{{ field.value }}</span>
      </div>
      <div class="flex shrink-0 items-center gap-1.5 rounded border border-border px-2 py-0.5 text-[11px] leading-4 text-muted-foreground">
        <Paperclip class="h-3 w-3 shrink-0" />
        <span class="min-w-0 flex-1 truncate">quote.pdf from Drive</span>
      </div>
    </div>

    <div
      class="flex shrink-0 items-center gap-1.5 rounded border border-dashed px-2 py-0.5 text-[11px] leading-4 transition-colors duration-500"
      :class="sent ? 'text-foreground' : 'border-border text-muted-foreground'"
      :style="sent ? { borderColor: `hsl(var(${sender.color}) / 0.6)` } : {}"
    >
      <Check
        v-if="sent"
        class="h-3 w-3 shrink-0 text-[hsl(var(--success))]"
      />
      <SendHorizontal
        v-else
        class="h-3 w-3 shrink-0"
      />
      <span class="min-w-0 truncate">{{ sent ? "status: sent" : "Ready to send" }}</span>
      <span class="ml-auto shrink-0 text-[10px] text-muted-foreground">{{ sender.sentFolder }}</span>
    </div>
    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
