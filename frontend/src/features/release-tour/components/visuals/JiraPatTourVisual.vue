<script setup lang="ts">
import { computed } from "vue";
import { KeyRound, ShieldCheck } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: Authentication is set to username and password · 1: it is switched to
// Personal Access Token · 2: the token is pasted · 3: Test Connection succeeds.
const step = useCycleStep(4, 1500);

const isPat = computed<boolean>(() => step.value >= 1);
const hasToken = computed<boolean>(() => step.value >= 2);
const connected = computed<boolean>(() => step.value === 3);

const caption = computed<string>(() => {
  if (step.value === 0) return "Jira Data Center / Server";
  if (step.value === 1) return "Authentication: Personal Access Token";
  if (step.value === 2) return "Paste the token, no username needed";
  return "Connected";
});
</script>

<template>
  <div class="flex h-full w-full flex-col justify-between rounded-lg bg-card p-3">
    <div class="flex items-center gap-2 text-[10px]">
      <span
        class="rounded-md border px-2 py-1 leading-none transition-colors duration-500"
        :class="
          isPat
            ? 'border-primary/60 bg-primary/10 text-foreground'
            : 'border-border/60 bg-background text-muted-foreground'
        "
      >
        {{ isPat ? "Personal Access Token" : "Username and password" }}
      </span>
    </div>
    <div
      class="flex items-center gap-2 rounded-md border px-2 py-2 text-[10px] transition-colors duration-500"
      :class="
        hasToken
          ? 'border-primary/60 bg-primary/10 text-foreground'
          : 'border-border bg-background text-muted-foreground'
      "
    >
      <KeyRound class="h-3 w-3" />
      <span>{{ hasToken ? "••••••••••••••••" : isPat ? "Paste token" : "jira-user" }}</span>
    </div>
    <div class="flex items-center justify-between text-[10px]">
      <span class="text-muted-foreground">{{ caption }}</span>
      <span
        class="flex items-center gap-1 rounded-md px-2 py-1 transition-colors duration-500"
        :class="connected ? 'bg-primary/15 text-primary' : 'text-muted-foreground'"
      >
        <ShieldCheck class="h-3 w-3" />
        Test
      </span>
    </div>
  </div>
</template>
