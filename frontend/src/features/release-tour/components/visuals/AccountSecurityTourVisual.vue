<script setup lang="ts">
import { computed } from "vue";
import { ShieldCheck, UserX } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: password · 1: scan the QR code · 2: enter the code · 3: an admin deactivates.
const step = useCycleStep(4, 1600);
const digits = ["4", "8", "2", "9", "1", "5"];

const caption = computed<string>(
  () =>
    [
      "A password sign-in, with two-factor turned on",
      "First time: scan the QR code with an authenticator",
      "Then enter the 6-digit code to get in",
      "Admins deactivate leavers: sessions end, triggers pause",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <ShieldCheck class="h-3 w-3" />
      {{ step === 3 ? "Settings · Users" : "Sign in to Heym" }}
    </div>

    <div class="flex min-h-0 flex-1 items-center justify-center rounded-md border border-border bg-muted/40 p-2.5">
      <div
        v-if="step === 0"
        class="w-full space-y-1.5"
      >
        <div class="rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground">
          ada@acme.example
        </div>
        <div class="rounded border border-border bg-background px-2 py-1 text-[11px] tracking-widest text-foreground">
          ••••••••••
        </div>
      </div>

      <div
        v-else-if="step === 1"
        class="grid h-20 w-20 grid-cols-5 gap-0.5 rounded bg-white p-1.5"
      >
        <span
          v-for="cell in 25"
          :key="cell"
          class="rounded-[1px]"
          :class="(cell * 7) % 3 === 0 || cell % 5 === 1 ? 'bg-black' : 'bg-transparent'"
        />
      </div>

      <div
        v-else-if="step === 2"
        class="flex gap-1"
      >
        <span
          v-for="(digit, index) in digits"
          :key="index"
          class="flex h-7 w-6 items-center justify-center rounded border border-primary/40 bg-background font-mono text-xs text-foreground"
        >
          {{ digit }}
        </span>
      </div>

      <div
        v-else
        class="flex w-full items-center justify-between gap-2 rounded border border-border bg-background px-2 py-1.5"
      >
        <div class="min-w-0">
          <div class="truncate text-[11px] font-medium text-foreground">
            Sam Leaver
          </div>
          <div class="truncate text-[10px] text-muted-foreground">
            sam@acme.example
          </div>
        </div>
        <span class="inline-flex shrink-0 items-center gap-1 rounded-full bg-destructive/10 px-1.5 py-0.5 text-[10px] text-destructive">
          <UserX class="h-2.5 w-2.5" />
          Deactivated
        </span>
      </div>
    </div>

    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
