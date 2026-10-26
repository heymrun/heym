<script setup lang="ts">
import { Check } from "lucide-vue-next";

export type AgentSuiteStep = 1 | 2 | 3 | 4;

// Step 4 is a saved suite's results, which has no stepper.
interface Props {
  step: AgentSuiteStep;
}

defineProps<Props>();

const emit = defineEmits<{
  (e: "go", step: AgentSuiteStep): void;
}>();

const STEPS: { step: AgentSuiteStep; label: string }[] = [
  { step: 1, label: "Agent" },
  { step: 2, label: "Baseline" },
  { step: 3, label: "Checks" },
];
</script>

<template>
  <nav class="flex gap-1 overflow-x-auto border-b border-border/40 px-4 py-2">
    <button
      v-for="item in STEPS"
      :key="item.step"
      type="button"
      class="flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors"
      :class="step === item.step
        ? 'bg-muted text-foreground'
        : 'text-muted-foreground hover:text-foreground'"
      :data-testid="`agent-suite-step-${item.step}`"
      @click="emit('go', item.step)"
    >
      <span
        class="flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold"
        :class="step > item.step ? 'bg-primary text-primary-foreground' : 'border border-border'"
      >
        <Check
          v-if="step > item.step"
          class="h-3 w-3"
        />
        <template v-else>{{ item.step }}</template>
      </span>
      {{ item.label }}
    </button>
  </nav>
</template>
