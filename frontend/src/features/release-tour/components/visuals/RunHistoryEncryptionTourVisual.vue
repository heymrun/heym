<script setup lang="ts">
import { computed } from "vue";
import { CheckCircle2, Lock, LockOpen, ScrollText } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the setting is off · 1: turned on in workflow settings · 2: the next run is
// locked in History · 3: confirm the unlock · 4: the run opens and the audit log gets a line.
const step = useCycleStep(5, 2000);

const enabled = computed<boolean>(() => step.value >= 1);
const locked = computed<boolean>(() => step.value === 2 || step.value === 3);
const confirming = computed<boolean>(() => step.value === 3);
const unlocked = computed<boolean>(() => step.value === 4);
const showRun = computed<boolean>(() => step.value >= 2);

const caption = computed<string>(() => {
  if (step.value === 0) return "Encrypt run history in the workflow settings";
  if (step.value === 1) return "Runs from now on are stored encrypted";
  if (step.value === 2) return "History shows the run with a lock";
  if (step.value === 3) return "Unlocking asks first and is audited";
  return "Decrypted on the server, written to the audit log";
});
</script>

<template>
  <div class="relative flex h-full w-full flex-col gap-1.5 rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-center gap-1.5 rounded border border-border px-2 py-1 text-[11px] leading-4">
      <Lock class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span class="font-medium text-foreground">Encrypt run history</span>
      <span
        class="ml-auto inline-flex h-3.5 w-6 shrink-0 items-center rounded-full transition-colors duration-500"
        :class="enabled ? 'bg-primary' : 'bg-muted-foreground/30'"
      >
        <span
          class="inline-block h-2.5 w-2.5 rounded-full bg-white transition-transform duration-500"
          :class="enabled ? 'translate-x-3' : 'translate-x-0.5'"
        />
      </span>
    </div>

    <div class="flex min-h-0 flex-1 gap-1.5 overflow-hidden">
      <div class="flex w-[38%] shrink-0 flex-col gap-1">
        <span class="text-[10px] leading-3 text-muted-foreground">History</span>
        <Transition
          enter-from-class="opacity-0 -translate-y-1"
          enter-active-class="transition-all duration-300"
        >
          <div
            v-if="showRun"
            class="flex items-center gap-1 rounded border border-primary/50 bg-primary/10 px-1.5 py-0.5 text-[10px] leading-4"
          >
            <CheckCircle2 class="h-3 w-3 shrink-0 text-[hsl(var(--success))]" />
            <span class="min-w-0 flex-1 truncate text-foreground">Payroll intake</span>
            <Lock class="h-2.5 w-2.5 shrink-0 text-primary dark:text-violet-300" />
          </div>
        </Transition>
        <div class="flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] leading-4 text-muted-foreground">
          <CheckCircle2 class="h-3 w-3 shrink-0" />
          <span class="min-w-0 flex-1 truncate">Payroll intake</span>
        </div>
      </div>

      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <span class="text-[10px] leading-3 text-muted-foreground">Run</span>
        <div
          v-if="!showRun"
          class="flex flex-1 items-center justify-center rounded border border-dashed border-border text-[10px] text-muted-foreground"
        >
          Select a run
        </div>
        <div
          v-else-if="locked"
          class="flex items-center gap-1.5 rounded border border-border bg-muted/40 px-2 py-1 text-[10px] leading-4"
        >
          <Lock class="h-3 w-3 shrink-0 text-primary dark:text-violet-300" />
          <span class="min-w-0 flex-1 truncate text-foreground">Encrypted run</span>
          <span
            class="inline-flex shrink-0 items-center gap-0.5 rounded border px-1 transition-colors duration-300"
            :class="confirming ? 'border-primary text-primary dark:text-violet-300' : 'border-border text-foreground'"
          >
            <LockOpen class="h-2.5 w-2.5" />Unlock
          </span>
        </div>
        <template v-else-if="unlocked">
          <div class="flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-[10px] leading-4 text-primary dark:text-violet-300">
            <LockOpen class="h-2.5 w-2.5 shrink-0" />
            <span class="truncate">Unlocked, written to the audit log</span>
          </div>
          <div class="rounded bg-muted/40 px-2 py-0.5 font-mono text-[10px] leading-4 text-foreground">
            <div class="truncate">
              "email": "jane@example.com"
            </div>
            <div class="truncate">
              "iban": "DE89 3704 0044"
            </div>
          </div>
        </template>
      </div>
    </div>

    <div
      class="flex shrink-0 items-center gap-1.5 rounded border border-dashed px-2 py-0.5 font-mono text-[10px] leading-4 transition-colors duration-500"
      :class="unlocked ? 'border-primary/60 text-foreground' : 'border-border text-muted-foreground'"
    >
      <ScrollText class="h-3 w-3 shrink-0" />
      <span class="min-w-0 truncate">{{ unlocked ? "workflow.history_unlock outcome=success" : "audit log" }}</span>
    </div>
    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>

    <Transition
      enter-from-class="opacity-0 scale-95"
      leave-to-class="opacity-0 scale-95"
      enter-active-class="transition-all duration-300"
      leave-active-class="transition-all duration-200"
    >
      <div
        v-if="confirming"
        class="absolute inset-x-6 top-1/3 rounded-md border border-border bg-card p-2 text-[10px] leading-4 shadow-lg"
      >
        <p class="font-medium text-foreground">
          Unlock this run?
        </p>
        <p class="text-muted-foreground">
          Your account and the time go to the audit log.
        </p>
        <div class="mt-1 flex justify-end gap-1">
          <span class="rounded border border-border px-1.5 text-muted-foreground">Cancel</span>
          <span class="rounded bg-primary px-1.5 text-primary-foreground">Unlock</span>
        </div>
      </div>
    </Transition>
  </div>
</template>
