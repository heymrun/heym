<script setup lang="ts">
import { Play, Square } from "lucide-vue-next";

import type { QuickDrawerInputField } from "@/types/quickDrawer";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";

defineProps<{
  fields: QuickDrawerInputField[];
  values: Record<string, string>;
  running: boolean;
}>();

const emit = defineEmits<{
  updateInput: [key: string, value: string];
  run: [];
  stop: [];
}>();
</script>

<template>
  <section class="rounded-3xl border border-border/60 bg-background/80 p-4">
    <div class="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
      Inputs
    </div>

    <div class="mt-4 space-y-3">
      <template v-if="fields.length > 0">
        <div
          v-for="field in fields"
          :key="field.key"
          class="space-y-1.5"
        >
          <label
            :for="`quick-drawer-input-${field.key}`"
            class="block text-sm font-medium text-foreground"
          >
            {{ field.key }}
          </label>
          <Input
            :id="`quick-drawer-input-${field.key}`"
            :model-value="values[field.key] ?? ''"
            :placeholder="field.defaultValue || `Enter ${field.key}`"
            @update:model-value="(value) => emit('updateInput', field.key, value)"
          />
        </div>
      </template>
      <div
        v-else
        class="rounded-2xl border border-dashed border-border/60 px-4 py-3 text-sm text-muted-foreground"
      >
        This workflow does not require any input fields.
      </div>
    </div>

    <div class="mt-4 flex items-center gap-3">
      <Button
        v-if="!running"
        variant="gradient"
        class="flex-1"
        data-testid="quick-workflow-run-start"
        @click="emit('run')"
      >
        <Play class="h-4 w-4" />
        <span>Run Workflow</span>
      </Button>
      <Button
        v-else
        variant="destructive"
        class="flex-1"
        data-testid="quick-workflow-run-stop"
        @click="emit('stop')"
      >
        <Square class="h-4 w-4" />
        <span>Stop Workflow</span>
      </Button>
    </div>
  </section>
</template>
