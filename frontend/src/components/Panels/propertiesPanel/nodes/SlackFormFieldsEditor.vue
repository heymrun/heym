<script setup lang="ts">
import { Plus, Trash2 } from "lucide-vue-next";

import type { SlackFormField } from "@/types/workflow";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";

const MAX_FIELDS = 10;
const TYPE_OPTIONS = [
  { value: "text", label: "Short text" },
  { value: "multiline", label: "Long text" },
  { value: "number", label: "Number" },
  { value: "email", label: "Email" },
  { value: "date", label: "Date" },
  { value: "select", label: "Choice" },
];

const props = defineProps<{ fields: SlackFormField[] }>();
const emit = defineEmits<{ (e: "update", fields: SlackFormField[]): void }>();

function update(index: number, patch: Partial<SlackFormField>): void {
  emit(
    "update",
    props.fields.map((field, i) => (i === index ? { ...field, ...patch } : field)),
  );
}

function add(): void {
  emit("update", [
    ...props.fields,
    { label: "", name: "", type: "text", required: true, options: "" },
  ]);
}

function remove(index: number): void {
  emit("update", props.fields.filter((_field, i) => i !== index));
}
</script>

<template>
  <div class="space-y-2">
    <Label>Form fields</Label>
    <div
      v-for="(field, index) in fields"
      :key="index"
      class="space-y-1.5 rounded-md border border-border p-2"
    >
      <div class="grid grid-cols-[1fr_7rem_auto] items-center gap-1.5">
        <Input
          :model-value="field.label"
          placeholder="Label"
          :aria-label="`Field ${index + 1} label`"
          @update:model-value="update(index, { label: String($event) })"
        />
        <Select
          :model-value="field.type"
          :options="TYPE_OPTIONS"
          @update:model-value="update(index, { type: ($event ?? 'text') as SlackFormField['type'] })"
        />
        <button
          type="button"
          class="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive"
          :aria-label="`Remove field ${index + 1}`"
          @click="remove(index)"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </button>
      </div>
      <div class="grid grid-cols-[1fr_auto] items-center gap-1.5">
        <Input
          :model-value="field.name"
          placeholder="Output key (from the label when empty)"
          :aria-label="`Field ${index + 1} output key`"
          @update:model-value="update(index, { name: String($event) })"
        />
        <label class="flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            :checked="field.required"
            @change="update(index, { required: ($event.target as HTMLInputElement).checked })"
          >
          Required
        </label>
      </div>
      <Input
        v-if="field.type === 'select'"
        :model-value="field.options"
        placeholder="Choices, comma separated"
        :aria-label="`Field ${index + 1} choices`"
        @update:model-value="update(index, { options: String($event) })"
      />
    </div>
    <button
      v-if="fields.length < MAX_FIELDS"
      type="button"
      class="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
      @click="add"
    >
      <Plus class="h-3.5 w-3.5" />Add field
    </button>
    <p class="text-xs text-muted-foreground">
      The run continues with $label.values.&lt;output key&gt; for each field.
    </p>
  </div>
</template>
