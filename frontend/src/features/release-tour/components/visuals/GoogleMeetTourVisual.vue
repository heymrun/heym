<script setup lang="ts">
import { CalendarClock, CheckCircle2, Mail, Video } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

const step = useCycleStep(3, 2400);
const captions = ["Find a free time in your calendar", "Your visitor chooses a time and enters their email", "Send a Meet invitation from your Google account"];
</script>

<template>
  <div class="flex h-full flex-col gap-3 rounded-lg bg-card p-4">
    <div class="flex items-center gap-2 text-xs font-medium">
      <CalendarClock class="h-4 w-4 text-primary" /> Book a calendar with me
    </div>
    <div class="grid grid-cols-3 gap-2">
      <div
        v-for="(time, index) in ['10:00', '11:30', '14:00']"
        :key="time"
        class="rounded-md border px-2 py-3 text-center text-xs transition-colors duration-500"
        :class="step > 0 && index === 1 ? 'border-primary bg-primary/15 text-primary dark:bg-primary/25 dark:text-brand-primary-soft' : 'border-border bg-background'"
      >
        {{ time }}
      </div>
    </div>
    <div
      class="flex items-center gap-2 rounded-md border border-border bg-background p-3 text-xs transition-opacity duration-500"
      :class="step > 0 ? 'opacity-100' : 'opacity-30'"
    >
      <Mail class="h-4 w-4 text-muted-foreground" /> visitor@example.com
    </div>
    <div
      class="flex items-center gap-2 text-xs transition-opacity duration-500"
      :class="step === 2 ? 'opacity-100' : 'opacity-30'"
    >
      <Video class="h-4 w-4 text-primary" /> Google Meet
      <CheckCircle2 class="ml-auto h-4 w-4 text-primary" /> Invitation sent
    </div>
    <p class="mt-auto text-[11px] text-muted-foreground">
      {{ captions[step] }}
    </p>
  </div>
</template>
