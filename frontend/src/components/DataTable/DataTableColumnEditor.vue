<script setup lang="ts">
import { ref } from "vue";
import { ChevronDown } from "lucide-vue-next";

import type { DataTableColumn } from "@/types/dataTable";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";

const props = defineProps<{ column: DataTableColumn | null }>();
const emit = defineEmits<{ save: [column: DataTableColumn]; close: [] }>();

const name = ref(props.column?.name ?? "");
const type = ref(props.column?.type ?? "string");
const required = ref(props.column?.required ?? false);
const defaultValue = ref(props.column?.defaultValue != null ? String(props.column.defaultValue) : "");
const unique = ref(props.column?.unique ?? false);

function handleSave() {
  if (!name.value.trim()) return;
  emit("save", {
    id: props.column?.id ?? crypto.randomUUID(),
    name: name.value.trim(),
    type: type.value as DataTableColumn["type"],
    required: required.value,
    defaultValue: defaultValue.value || null,
    unique: unique.value,
    order: props.column?.order ?? 0,
  });
}
</script>

<template>
  <Dialog
    :open="true"
    :title="column ? 'Edit Column' : 'Add Column'"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-4">
      <div>
        <Label>Name</Label>
        <Input
          v-model="name"
          placeholder="Column name"
          class="mt-1"
          @keydown.enter="handleSave"
        />
      </div>

      <div>
        <Label>Type</Label>
        <div class="relative mt-1">
          <select
            v-model="type"
            class="w-full appearance-none rounded border bg-background px-3 py-2 pr-8 text-sm"
          >
            <option value="string">
              String
            </option>
            <option value="number">
              Number
            </option>
            <option value="boolean">
              Boolean
            </option>
            <option value="date">
              Date
            </option>
            <option value="json">
              JSON
            </option>
          </select>
          <ChevronDown class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        </div>
      </div>

      <div class="flex items-center gap-4">
        <label class="flex items-center gap-2 text-sm">
          <input
            v-model="required"
            type="checkbox"
            class="rounded"
          >
          Required
        </label>
        <label class="flex items-center gap-2 text-sm">
          <input
            v-model="unique"
            type="checkbox"
            class="rounded"
          >
          Unique
        </label>
      </div>

      <div>
        <Label>Default Value (optional)</Label>
        <Input
          v-model="defaultValue"
          placeholder="Default value"
          class="mt-1"
        />
      </div>

      <div class="flex justify-end">
        <Button
          :disabled="!name.trim()"
          @click="handleSave"
        >
          {{ column ? "Update" : "Add" }}
        </Button>
      </div>
    </div>
  </Dialog>
</template>
