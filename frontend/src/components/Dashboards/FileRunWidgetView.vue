<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
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
  /** A file to run, with the values of the workflow's text input fields (none without any). */
  drop: [file: File, values: Record<string, string>];
  /** The values of the workflow's start fields; empty for a workflow without inputs. */
  run: [values: Record<string, string>];
}>();

// The `run` slot replaces the Run button; it gets `disabled` and must submit the form.
defineSlots<{ run?: (props: { disabled: boolean }) => unknown }>();

const values = reactive<Record<string, string>>({});
// A file waiting for Run, when the workflow also has text input fields to fill first.
const chosen = ref<File | null>(null);

const mode = computed(() => props.payload.mode ?? "file");
const fields = computed(() => props.payload.input_fields ?? []);
const fileWithFields = computed(() => mode.value === "file" && fields.value.length > 0);
const running = computed(() => props.runState.status === "running");
const canRun = computed(
  () => !running.value && (mode.value !== "file" || chosen.value !== null),
);

// Each field starts from its default; a new payload starts the form again.
watch(
  fields,
  (next) => {
    for (const key of Object.keys(values)) delete values[key];
    for (const field of next) values[field.key] = field.defaultValue ?? "";
    chosen.value = null;
  },
  { immediate: true },
);

function select(selected: File | null): void {
  if (fileWithFields.value) chosen.value = selected;
  else if (selected) emit("drop", selected, {});
}

function submit(): void {
  if (!canRun.value) return;
  if (mode.value !== "file") emit("run", { ...values });
  else if (chosen.value) emit("drop", chosen.value, { ...values });
}
</script>

<template>
  <div
    class="h-full space-y-3 overflow-auto"
    data-testid="file-run-widget"
  >
    <FileDropInput
      v-if="mode === 'file' && !fileWithFields"
      :label="payload.file_label ?? 'file'"
      :file="file"
      :allowed-types="payload.allowed_types ?? []"
      :max-size-mb="payload.max_size_mb ?? 0"
      :disabled="running"
      @select="select"
    />
    <form
      v-else
      class="space-y-2"
      @submit.prevent="submit"
    >
      <FileDropInput
        v-if="fileWithFields"
        :label="payload.file_label ?? 'file'"
        :file="chosen ?? file"
        :allowed-types="payload.allowed_types ?? []"
        :max-size-mb="payload.max_size_mb ?? 0"
        :disabled="running"
        @select="select"
      />
      <label
        v-for="field in fields"
        :key="field.key"
        class="block text-xs font-medium text-muted-foreground"
      >
        {{ field.key }}
        <Input
          v-model="values[field.key]"
          class="mt-1"
          :disabled="running"
        />
      </label>
      <slot
        name="run"
        :disabled="!canRun"
      >
        <Button
          type="submit"
          size="sm"
          :disabled="!canRun"
        >
          <Play class="h-3.5 w-3.5 fill-current" />
          Run
        </Button>
      </slot>
    </form>
    <QuickWorkflowRunResult
      v-if="runState.status !== 'idle'"
      :run-state="runState"
    />
  </div>
</template>
