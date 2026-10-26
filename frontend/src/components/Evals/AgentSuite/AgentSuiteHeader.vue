<script setup lang="ts">
import { ExternalLink, X } from "lucide-vue-next";

import Input from "@/components/ui/Input.vue";

export type AgentSuiteView = "results" | "baseline" | "checks";

interface Props {
  name: string;
  /** The workflow that holds the agent, once one is picked. */
  workflowId: string;
  /** A saved suite switches views here; a new one follows the stepper instead. */
  view?: AgentSuiteView | null;
}

withDefaults(defineProps<Props>(), { view: null });

const emit = defineEmits<{
  (e: "update:name", value: string): void;
  (e: "update:view", value: AgentSuiteView): void;
}>();

const VIEWS: { value: AgentSuiteView; label: string }[] = [
  { value: "results", label: "Results" },
  { value: "baseline", label: "Baseline" },
  { value: "checks", label: "Edit checks" },
];
</script>

<template>
  <div class="flex flex-wrap items-center gap-3 border-b border-border/40 px-4 py-3">
    <!-- Keeps Esc for clearing the field instead of the global overlay dismiss. -->
    <div
      class="group relative w-full max-w-sm"
      data-heym-inline-edit
    >
      <Input
        :model-value="name"
        placeholder="Suite name"
        class="pr-10 font-medium"
        data-testid="agent-suite-name"
        @update:model-value="(value) => emit('update:name', value)"
        @keydown.esc.stop.prevent="emit('update:name', '')"
      />
      <button
        v-if="name"
        type="button"
        class="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
        :class="view ? 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100' : ''"
        aria-label="Clear suite name"
        title="Clear (Esc)"
        data-testid="agent-suite-name-clear"
        @click="emit('update:name', '')"
      >
        <X class="h-4 w-4" />
      </button>
    </div>
    <div
      v-if="view"
      class="ml-auto inline-flex rounded-lg border border-border bg-muted/40 p-0.5"
    >
      <button
        v-for="item in VIEWS"
        :key="item.value"
        type="button"
        class="rounded-md px-3 py-1.5 text-sm transition-colors"
        :class="view === item.value
          ? 'bg-background text-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground'"
        :data-testid="`agent-suite-view-${item.value}`"
        @click="emit('update:view', item.value)"
      >
        {{ item.label }}
      </button>
    </div>
    <!-- A new tab, so a suite being set up is not lost. -->
    <RouterLink
      v-if="workflowId"
      :to="{ name: 'editor', params: { id: workflowId } }"
      target="_blank"
      class="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-border px-3 text-sm text-foreground transition-colors hover:bg-muted"
      :class="view ? '' : 'ml-auto'"
      data-testid="agent-suite-go-to-workflow"
    >
      <ExternalLink class="h-3.5 w-3.5" />
      Go to workflow
    </RouterLink>
  </div>
</template>
