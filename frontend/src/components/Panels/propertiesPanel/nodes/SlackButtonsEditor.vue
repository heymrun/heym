<script setup lang="ts">
import { Plus, Trash2 } from "lucide-vue-next";

import type { SlackButton } from "@/types/workflow";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";

const MAX_BUTTONS = 5;
const STYLE_OPTIONS = [
  { value: "", label: "Default" },
  { value: "primary", label: "Primary" },
  { value: "danger", label: "Danger" },
];

const props = defineProps<{ buttons: SlackButton[] }>();
const emit = defineEmits<{ (e: "update", buttons: SlackButton[]): void }>();

function update(index: number, patch: Partial<SlackButton>): void {
  emit(
    "update",
    props.buttons.map((button, i) => (i === index ? { ...button, ...patch } : button)),
  );
}

function add(): void {
  emit("update", [...props.buttons, { label: "", value: "", style: "" }]);
}

function remove(index: number): void {
  emit("update", props.buttons.filter((_button, i) => i !== index));
}
</script>

<template>
  <div class="space-y-2">
    <Label>Buttons</Label>
    <div
      v-for="(button, index) in buttons"
      :key="index"
      class="grid grid-cols-[1fr_1fr_6.5rem_auto] items-center gap-1.5"
    >
      <Input
        :model-value="button.label"
        placeholder="Label"
        :aria-label="`Button ${index + 1} label`"
        @update:model-value="update(index, { label: String($event) })"
      />
      <Input
        :model-value="button.value"
        placeholder="Value"
        :aria-label="`Button ${index + 1} value`"
        @update:model-value="update(index, { value: String($event) })"
      />
      <Select
        :model-value="button.style"
        :options="STYLE_OPTIONS"
        @update:model-value="update(index, { style: ($event ?? '') as SlackButton['style'] })"
      />
      <button
        type="button"
        class="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive"
        :aria-label="`Remove button ${index + 1}`"
        @click="remove(index)"
      >
        <Trash2 class="h-3.5 w-3.5" />
      </button>
    </div>
    <button
      v-if="buttons.length < MAX_BUTTONS"
      type="button"
      class="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
      @click="add"
    >
      <Plus class="h-3.5 w-3.5" />Add button
    </button>
    <p class="text-xs text-muted-foreground">
      Up to five. The run continues with $label.choice.value of the button pressed.
    </p>
  </div>
</template>
