<script setup lang="ts">
import { computed } from "vue";
import { ArrowRight, Clock, FileText, FolderOpen, Play, Sheet } from "lucide-vue-next";

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

const DRIVE = "hsl(var(--node-google-drive))";
const SHEETS = "hsl(var(--node-google-sheets))";
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-1.5 text-[11px] leading-4 text-muted-foreground">
      <Clock class="h-3.5 w-3.5" />Heym checks Drive and Sheets every minute
    </div>
    <div class="flex flex-col gap-3">
      <div class="flex items-center gap-2">
        <div class="flex min-w-0 flex-1 items-center gap-2.5 rounded-md border border-border/60 bg-background px-2.5 py-2.5">
          <span
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md"
            :style="{ backgroundColor: 'hsl(var(--node-google-drive) / 0.15)', color: DRIVE }"
          >
            <FolderOpen class="h-4 w-4" />
          </span>
          <span class="min-w-0">
            <span class="block text-[11px] font-semibold leading-4 text-foreground">Google Drive Trigger</span>
            <span class="flex items-center gap-1 text-[10px] leading-4 text-muted-foreground">
              Intake
              <span
                class="flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] leading-none transition-opacity duration-500"
                :class="fileLanded ? 'bg-primary/15 text-foreground opacity-100' : 'opacity-0'"
              >
                <FileText class="h-2.5 w-2.5" />contract.pdf
              </span>
            </span>
          </span>
        </div>
        <ArrowRight
          class="h-4 w-4 shrink-0 transition-colors duration-500"
          :class="driveRun ? 'text-primary' : 'text-muted-foreground/50'"
        />
        <span
          class="flex items-center gap-1 rounded-md border px-2.5 py-2 text-[10px] leading-none transition-colors duration-500"
          :class="driveRun ? 'border-primary/60 bg-primary/10 text-foreground' : 'border-border/60 bg-background text-muted-foreground'"
        >
          <Play class="h-3 w-3" />run
        </span>
      </div>

      <div class="flex items-center gap-2">
        <div class="flex min-w-0 flex-1 items-center gap-2.5 rounded-md border border-border/60 bg-background px-2.5 py-2.5">
          <span
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md"
            :style="{ backgroundColor: 'hsl(var(--node-google-sheets) / 0.15)', color: SHEETS }"
          >
            <Sheet class="h-4 w-4" />
          </span>
          <span class="min-w-0">
            <span class="block text-[11px] font-semibold leading-4 text-foreground">Google Sheets Trigger</span>
            <span class="flex items-center gap-1 text-[10px] leading-4 text-muted-foreground">
              Leads
              <span
                class="rounded px-1 py-0.5 text-[9px] leading-none transition-opacity duration-500"
                :class="rowAdded ? 'bg-primary/15 text-foreground opacity-100' : 'opacity-0'"
              >
                row 14 added
              </span>
            </span>
          </span>
        </div>
        <ArrowRight
          class="h-4 w-4 shrink-0 transition-colors duration-500"
          :class="sheetRun ? 'text-primary' : 'text-muted-foreground/50'"
        />
        <span
          class="flex items-center gap-1 rounded-md border px-2.5 py-2 text-[10px] leading-none transition-colors duration-500"
          :class="sheetRun ? 'border-primary/60 bg-primary/10 text-foreground' : 'border-border/60 bg-background text-muted-foreground'"
        >
          <Play class="h-3 w-3" />run
        </span>
      </div>
    </div>

    <p class="mt-auto truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
