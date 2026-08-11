<script setup lang="ts">
import { computed } from "vue";

import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { cn } from "@/lib/utils";
import type { AlertScope } from "@/types/alerts";

interface WorkflowOption {
  value: string;
  label: string;
}

interface Props {
  scope: AlertScope;
  workflowId: string | null;
  workflows: WorkflowOption[];
}

const props = defineProps<Props>();
const emit = defineEmits<{
  "update:scope": [value: AlertScope];
  "update:workflowId": [value: string | null];
}>();

const selectedWorkflow = computed({
  get: (): string | undefined => props.workflowId ?? undefined,
  set: (value: string | undefined): void => emit("update:workflowId", value ?? null),
});

function selectScope(scope: AlertScope): void {
  emit("update:scope", scope);
  if (scope === "system") emit("update:workflowId", null);
}
</script>

<template>
  <div class="space-y-4">
    <div class="grid gap-3 sm:grid-cols-2">
      <button
        type="button"
        :class="
          cn(
            'rounded-lg border p-4 text-left transition-colors',
            scope === 'workflow'
              ? 'border-primary bg-primary/5'
              : 'border-border hover:border-primary/50',
          )
        "
        @click="selectScope('workflow')"
      >
        <div class="font-medium">
          One workflow
        </div>
        <div class="mt-1 text-xs text-muted-foreground">
          Watch a single workflow.
        </div>
      </button>

      <button
        type="button"
        :class="
          cn(
            'rounded-lg border p-4 text-left transition-colors',
            scope === 'system'
              ? 'border-primary bg-primary/5'
              : 'border-border hover:border-primary/50',
          )
        "
        @click="selectScope('system')"
      >
        <div class="font-medium">
          All my workflows
        </div>
        <div class="mt-1 text-xs text-muted-foreground">
          Every workflow you can access, measured together.
        </div>
      </button>
    </div>

    <div
      v-if="scope === 'workflow'"
      class="space-y-2"
    >
      <Label for="alert-workflow">Workflow</Label>
      <SearchableSelect
        id="alert-workflow"
        v-model="selectedWorkflow"
        :options="workflows"
        placeholder="Choose a workflow..."
      />
    </div>
  </div>
</template>
