<script setup lang="ts">
import { computed } from "vue";
import { AudioLines, Languages, Repeat } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the recording · 1: the language is detected · 2: the transcript.
const step = useCycleStep(3, 2400);

const bars = [35, 70, 50, 90, 40, 75, 55, 95, 45, 65, 30, 80, 50, 70, 40, 60];

const segments = [
  { time: "0:00", text: "Hi, I am calling about order 2026." },
  { time: "0:04", text: "The delivery arrived on Wednesday." },
  { time: "0:09", text: "Please send the invoice by email." },
];

const caption = computed<string>(
  () =>
    [
      "Point the Converter at a voice note in Drive",
      "One model detects the spoken language",
      "The transcript is ready for the next node",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <Repeat class="h-3 w-3" />
      Converter · Audio → Text
      <span
        class="ml-auto flex items-center gap-1 transition-opacity duration-500"
        :class="step > 0 ? 'opacity-100' : 'opacity-0'"
      >
        <Languages class="h-3 w-3 text-primary" />
        English (en)
      </span>
    </div>

    <div class="flex items-center gap-2 rounded-md border border-border bg-background px-2.5 py-2">
      <AudioLines class="h-3.5 w-3.5 shrink-0 text-primary" />
      <span class="shrink-0 text-[11px] leading-4 text-foreground">voice-note.ogg</span>
      <div class="flex h-5 flex-1 items-center gap-0.5">
        <span
          v-for="(height, index) in bars"
          :key="index"
          class="w-full rounded-full transition-colors duration-500"
          :class="step > 0 ? 'bg-primary' : 'bg-muted-foreground/40'"
          :style="{ height: `${height}%` }"
        />
      </div>
      <span class="shrink-0 text-[10px] leading-4 text-muted-foreground">0:12</span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1">
      <div
        v-for="segment in segments"
        :key="segment.time"
        class="flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-[11px] leading-4 transition-opacity duration-500"
        :class="step === 2 ? 'opacity-100' : 'opacity-0'"
      >
        <span class="shrink-0 font-mono text-[10px] text-muted-foreground">{{ segment.time }}</span>
        <span class="truncate text-foreground">{{ segment.text }}</span>
      </div>
    </div>

    <p class="shrink-0 text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
