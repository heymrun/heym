<script setup lang="ts">
import { computed } from "vue";
import { AudioLines, Database, FileText, Image, Loader2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

type FileState = "dropped" | "working" | "added";

// Mock UI only. 0: files dropped · 1: the image is read, audio transcribes · 2: all are sources.
const step = useCycleStep(3, 2400);

const files = [
  { name: "receipt.jpg", icon: Image, quick: true },
  { name: "burak.akgun", icon: FileText, quick: true },
  { name: "support-call.mp3", icon: AudioLines, quick: false },
];

const caption = computed<string>(
  () =>
    [
      "Drop photos, recordings and text files on a store",
      "Images are read now, audio transcribes in the background",
      "Every file is a searchable source for RAG",
    ][step.value],
);

function state(quick: boolean): FileState {
  if (step.value === 0) return "dropped";
  if (step.value === 1) return quick ? "added" : "working";
  return "added";
}

const stateLabel: Record<FileState, string> = {
  dropped: "Dropped",
  working: "Transcribing",
  added: "Added",
};
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <Database class="h-3 w-3" />
      Vector store · Call notes
    </div>
    <div class="flex min-h-0 flex-1 flex-col gap-1.5">
      <div
        v-for="file in files"
        :key="file.name"
        class="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 transition-colors duration-500"
        :class="state(file.quick) === 'added' ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-border bg-background'"
      >
        <component
          :is="file.icon"
          class="h-3.5 w-3.5 shrink-0 text-primary"
        />
        <span class="truncate text-foreground">{{ file.name }}</span>
        <span class="ml-auto flex shrink-0 items-center gap-1 text-[10px] text-muted-foreground">
          <Loader2
            v-if="state(file.quick) === 'working'"
            class="h-3 w-3 animate-spin"
          />
          {{ stateLabel[state(file.quick)] }}
        </span>
      </div>
    </div>
    <p class="shrink-0 text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
