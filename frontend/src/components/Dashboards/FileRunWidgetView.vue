<script setup lang="ts">
import { reactive, watch } from "vue";
import { Play } from "lucide-vue-next";

import type { FileRunPayload } from "@/types/dashboard";
import type { QuickDrawerRunState } from "@/types/quickDrawer";
import QuickWorkflowRunResult from "@/components/Layout/QuickWorkflowRunResult.vue";
import Button from "@/components/ui/Button.vue";
import FileDropInput from "@/components/ui/FileDropInput.vue";
import Input from "@/components/ui/Input.vue";

const props = defineProps<{
  payload: FileRunPayload;
  /** The file of the last drop, while it runs and after. */
  file: File | null;
  runState: QuickDrawerRunState;
}>();

const emit = defineEmits<{
  drop: [file: File];
  /** The values of the workflow's start fields; empty for a workflow without inputs. */
  run: [values: Record<string, string>];
}>();

const values = reactive<Record<string, string>>({});

// Each field starts from its default; a new payload starts the form again.
watch(
  () => props.payload.input_fields,
  (fields) => {
    for (const key of Object.keys(values)) delete values[key];
    for (const field of fields ?? []) values[field.key] = field.defaultValue ?? "";
  },
  { immediate: true },
);
</script>

<template>
  <div
    class="h-full space-y-3 overflow-auto"
    data-testid="file-run-widget"
  >
    <FileDropInput
      v-if="(payload.mode ?? 'file') === 'file'"
      :label="payload.file_label ?? 'file'"
      :file="file"
      :allowed-types="payload.allowed_types ?? []"
      :max-size-mb="payload.max_size_mb ?? 0"
      :disabled="runState.status === 'running'"
      @select="(selected) => selected && emit('drop', selected)"
    />
    <form
      v-else
      class="space-y-2"
      @submit.prevent="emit('run', { ...values })"
    >
      <label
        v-for="field in payload.input_fields ?? []"
        :key="field.key"
        class="block text-xs font-medium text-muted-foreground"
      >
        {{ field.key }}
        <Input
          v-model="values[field.key]"
          class="mt-1"
          :disabled="runState.status === 'running'"
        />
      </label>
      <Button
        type="submit"
        size="sm"
        :disabled="runState.status === 'running'"
      >
        <Play class="h-3.5 w-3.5 fill-current" />
        Run
      </Button>
    </form>
    <QuickWorkflowRunResult
      v-if="runState.status !== 'idle'"
      :run-state="runState"
    />
  </div>
</template>
