<script setup lang="ts">
import { ExternalLink, FlaskConical } from "lucide-vue-next";

import type { EvalSuitePreview } from "@/types/chat";

interface Props {
  suites: EvalSuitePreview[];
}

defineProps<Props>();

const SUITE_TYPE_LABELS: Record<EvalSuitePreview["suiteType"], string> = {
  prompt: "Prompt suite",
  agent: "Agent suite",
};
</script>

<template>
  <div class="mt-3 flex flex-col gap-2">
    <div
      v-for="suite in suites"
      :key="suite.id"
      class="flex items-center justify-between gap-3 rounded-xl border border-border/50 bg-background/70 px-3 py-2.5"
      data-testid="chat-eval-suite-card"
    >
      <div class="flex min-w-0 items-center gap-2">
        <FlaskConical class="h-4 w-4 shrink-0 text-muted-foreground" />
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold">
            {{ suite.name }}
          </p>
          <p class="text-xs text-muted-foreground">
            {{ SUITE_TYPE_LABELS[suite.suiteType] }}
          </p>
        </div>
      </div>
      <a
        :href="suite.url"
        target="_blank"
        rel="noopener noreferrer"
        class="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
      >
        <ExternalLink class="h-3.5 w-3.5" />
        Open in Evals
      </a>
    </div>
  </div>
</template>
