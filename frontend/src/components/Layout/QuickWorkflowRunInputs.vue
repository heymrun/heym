<script setup lang="ts">
import { Play, Square } from "lucide-vue-next";

import type { QuickDrawerFileInput, QuickDrawerInputField } from "@/types/quickDrawer";
import Button from "@/components/ui/Button.vue";
import FileDropInput from "@/components/ui/FileDropInput.vue";
import Input from "@/components/ui/Input.vue";

withDefaults(
  defineProps<{
    fields: QuickDrawerInputField[];
    values: Record<string, string>;
    running: boolean;
    /** Set for a workflow with a File Upload trigger: the run needs a file. */
    fileInput?: QuickDrawerFileInput | null;
    file?: File | null;
  }>(),
  { fileInput: null, file: null },
);

const emit = defineEmits<{
  updateInput: [key: string, value: string];
  selectFile: [file: File | null];
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
      <FileDropInput
        v-if="fileInput"
        :label="fileInput.label"
        :file="file"
        :allowed-types="fileInput.allowedTypes"
        :max-size-mb="fileInput.maxSizeMb"
        :disabled="running"
        @select="(selected) => emit('selectFile', selected)"
      />
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
        v-else-if="!fileInput"
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
        :disabled="Boolean(fileInput) && !file"
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
