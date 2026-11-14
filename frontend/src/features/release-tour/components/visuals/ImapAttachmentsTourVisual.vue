<script setup lang="ts">
import { computed } from "vue";
import { Bot, Check, FileText, HardDrive, Inbox, Paperclip } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: an email with two attachments arrives · 1: the IMAP Trigger saves them
// to Drive · 2: an Agent reads the saved files through file_ids.
const step = useCycleStep(3, 2400);

interface MockAttachment {
  name: string;
  size: string;
}

const attachments: MockAttachment[] = [
  { name: "invoice-2026-118.pdf", size: "48 KB" },
  { name: "delivery-note.pdf", size: "31 KB" },
];

const saved = computed<boolean>(() => step.value >= 1);
const read = computed<boolean>(() => step.value === 2);

const caption = computed<string>(
  () =>
    [
      "A new email with attachments reaches the inbox",
      "Download attachments to Drive saves each file",
      "An Agent reads them through $invoiceInbox.file_ids",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-center gap-2 rounded-md border bg-background px-2.5 py-1 text-[11px] leading-4">
      <Inbox class="h-3 w-3 shrink-0 text-muted-foreground" />
      <span class="truncate text-foreground">Invoice 2026-118</span>
      <span class="ml-auto flex shrink-0 items-center gap-1 text-[10px] text-muted-foreground">
        <Paperclip class="h-3 w-3" />
        2
      </span>
    </div>
    <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden rounded-md border bg-background p-2">
      <div class="flex shrink-0 items-center gap-1.5 text-[10px] font-medium leading-4 text-muted-foreground">
        <HardDrive class="h-3 w-3" />
        <span>Drive</span>
        <span
          class="ml-auto rounded bg-primary/10 px-1 text-primary transition-opacity duration-500"
          :class="saved ? 'opacity-100' : 'opacity-0'"
        >
          file_ids: 2
        </span>
      </div>
      <div
        v-for="(item, index) in attachments"
        :key="item.name"
        class="flex shrink-0 items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] leading-4 transition-all duration-500"
        :class="saved ? 'translate-y-0 opacity-100' : 'translate-y-1 opacity-30'"
        :style="{ transitionDelay: saved ? `${index * 150}ms` : '0ms' }"
      >
        <FileText class="h-3 w-3 shrink-0 text-muted-foreground" />
        <span class="min-w-0 truncate text-foreground">{{ item.name }}</span>
        <span class="ml-auto shrink-0 text-[10px] text-muted-foreground">{{ item.size }}</span>
        <Check
          class="h-3 w-3 shrink-0 text-primary transition-opacity duration-500"
          :class="saved ? 'opacity-100' : 'opacity-0'"
        />
      </div>
      <div
        class="mt-auto flex shrink-0 items-center gap-1.5 rounded border border-dashed px-2 py-0.5 text-[11px] leading-4 transition-opacity duration-500"
        :class="read ? 'opacity-100' : 'opacity-0'"
      >
        <Bot class="h-3 w-3 shrink-0 text-primary" />
        <span class="min-w-0 truncate text-foreground">Acme Supplies · 1,240.00 · due 30 Nov</span>
      </div>
    </div>
    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
