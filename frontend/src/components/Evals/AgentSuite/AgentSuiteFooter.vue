<script setup lang="ts">
import type { AgentSuiteStep } from "@/components/Evals/AgentSuite/AgentSuiteStepper.vue";
import Button from "@/components/ui/Button.vue";

interface Props {
  step: AgentSuiteStep;
  isNew: boolean;
  canContinue: boolean;
  saving: boolean;
  error: string | null;
}

defineProps<Props>();

const emit = defineEmits<{
  (e: "go", step: AgentSuiteStep): void;
  (e: "create"): void;
  (e: "save"): void;
  (e: "cancel"): void;
}>();
</script>

<template>
  <div class="flex items-center justify-between gap-3 border-t border-border/40 px-4 py-3">
    <p class="text-xs text-destructive">
      {{ error }}
    </p>
    <div class="flex gap-2">
      <Button
        v-if="isNew"
        variant="ghost"
        data-testid="agent-suite-cancel"
        @click="emit('cancel')"
      >
        Cancel
      </Button>
      <Button
        v-if="step > 1 && isNew"
        variant="outline"
        @click="emit('go', (step - 1) as AgentSuiteStep)"
      >
        Back
      </Button>
      <Button
        v-if="isNew && step < 3"
        variant="gradient"
        :disabled="!canContinue"
        data-testid="agent-suite-next"
        @click="emit('go', (step + 1) as AgentSuiteStep)"
      >
        Next
      </Button>
      <Button
        v-else-if="isNew && step === 3"
        variant="gradient"
        :loading="saving"
        data-testid="agent-suite-create"
        @click="emit('create')"
      >
        Create suite
      </Button>
      <Button
        v-else-if="!isNew && step === 3"
        variant="gradient"
        :loading="saving"
        data-testid="agent-suite-save"
        @click="emit('save')"
      >
        Save checks
      </Button>
    </div>
  </div>
</template>
