<script setup lang="ts">
import { computed } from "vue";
import { FileText, FolderOpen, Play, Sheet } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: a file lands in the folder · 1: its run starts ·
// 2: a row is added to the sheet · 3: its run starts.
const step = useCycleStep(4, 1500);

const fileLanded = computed<boolean>(() => step.value <= 1);
const driveRun = computed<boolean>(() => step.value === 1);
const rowAdded = computed<boolean>(() => step.value >= 2);
const sheetRun = computed<boolean>(() => step.value === 3);

const caption = computed<string>(() => {
  if (step.value === 0) return "contract.pdf lands in Intake";
  if (step.value === 1) return "Google Drive Trigger starts one run";
  if (step.value === 2) return "A lead row is added to Leads";
  return "Google Sheets Trigger starts one run";
});
</script>

<template>
  <div class="flex h-full w-full flex-col justify-between rounded-lg bg-card p-3">
    <div class="flex items-center gap-2">
      <span
        class="flex items-center gap-1 rounded-md border border-border/60 bg-background px-2 py-1 text-[10px] leading-none text-muted-foreground"
      >
        <FolderOpen class="h-3 w-3" />
        Intake
        <span
          class="ml-1 flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] leading-none transition-opacity duration-500"
          :class="fileLanded ? 'bg-primary/15 text-foreground opacity-100' : 'opacity-0'"
        >
          <FileText class="h-2 w-2" />
          contract.pdf
        </span>
      </span>
      <span class="h-px w-4 bg-border" />
      <span
        class="flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] leading-none transition-colors duration-500"
        :class="
          driveRun
            ? 'border-primary/60 bg-primary/10 text-foreground'
            : 'border-border/60 bg-background text-muted-foreground'
        "
      >
        <Play class="h-3 w-3" />
        run
      </span>
    </div>

    <div class="flex items-center gap-2">
      <span
        class="flex items-center gap-1 rounded-md border border-border/60 bg-background px-2 py-1 text-[10px] leading-none text-muted-foreground"
      >
        <Sheet class="h-3 w-3" />
        Leads
        <span
          class="ml-1 rounded px-1 py-0.5 text-[9px] leading-none transition-opacity duration-500"
          :class="rowAdded ? 'bg-primary/15 text-foreground opacity-100' : 'opacity-0'"
        >
          row 14
        </span>
      </span>
      <span class="h-px w-4 bg-border" />
      <span
        class="flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] leading-none transition-colors duration-500"
        :class="
          sheetRun
            ? 'border-primary/60 bg-primary/10 text-foreground'
            : 'border-border/60 bg-background text-muted-foreground'
        "
      >
        <Play class="h-3 w-3" />
        run
      </span>
    </div>

    <p class="truncate text-[10px] leading-none text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
