<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Trash2 } from "lucide-vue-next";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import { useDashboardStore } from "@/stores/dashboard";
import type { RecordFormat } from "@/types/dashboard";
import DashboardShareSection from "./DashboardShareSection.vue";

const RECORD_FORMAT_OPTIONS: { value: RecordFormat; label: string }[] = [
  { value: "id", label: "IDs: letters, digits, - _ . (up to 128)" },
  { value: "number", label: "Numbers" },
  { value: "uuid", label: "UUIDs" },
  { value: "email", label: "Email addresses" },
];

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "deleted"): void;
}>();

const dashboardStore = useDashboardStore();
const name = ref("");
const recordFormat = ref<RecordFormat>("id");
const saving = ref(false);

watch(
  () => [props.open, dashboardStore.activeDashboard?.id] as const,
  ([open]) => {
    if (open && dashboardStore.activeDashboard) {
      name.value = dashboardStore.activeDashboard.name;
      recordFormat.value = dashboardStore.activeDashboard.record_format;
    }
  },
  { immediate: true },
);

const canSave = computed<boolean>(() => Boolean(name.value.trim()) && !saving.value);
// The API refuses to delete someone's only dashboard, so the button says so up front.
const canDelete = computed<boolean>(() => dashboardStore.ownedCount > 1);

async function submit(): Promise<void> {
  const dashboard = dashboardStore.activeDashboard;
  if (!canSave.value || !dashboard) return;
  saving.value = true;
  try {
    await dashboardStore.renameDashboard(dashboard.id, name.value.trim());
    if (recordFormat.value !== dashboard.record_format) {
      await dashboardStore.setRecordFormat(dashboard.id, recordFormat.value);
    }
    emit("close");
  } finally {
    saving.value = false;
  }
}

async function remove(): Promise<void> {
  const dashboard = dashboardStore.activeDashboard;
  if (!dashboard || !canDelete.value) return;
  if (!window.confirm(`Delete dashboard "${dashboard.name}" and all of its widgets?`)) return;
  await dashboardStore.deleteDashboard(dashboard.id);
  emit("deleted");
  emit("close");
}
</script>

<template>
  <Dialog
    :open="open"
    title="Dashboard settings"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-1">
      <Input
        v-model="name"
        placeholder="Dashboard name"
        data-testid="dashboard-settings-name"
        @keydown.enter="submit"
      />

      <div class="space-y-1">
        <label class="text-sm font-medium">Detail page records</label>
        <Select
          :model-value="recordFormat"
          :options="RECORD_FORMAT_OPTIONS"
          data-testid="dashboard-settings-record-format"
          @update:model-value="recordFormat = ($event as RecordFormat | undefined) ?? 'id'"
        />
        <p class="text-xs text-muted-foreground">
          The ?record= values this dashboard accepts when a row link opens it. Anything else is
          refused before a widget runs.
        </p>
      </div>

      <DashboardShareSection
        v-if="dashboardStore.activeDashboard"
        :key="dashboardStore.activeDashboard.id"
        :dashboard-id="dashboardStore.activeDashboard.id"
      />

      <div class="flex items-center justify-between gap-2 border-t border-border/60 pt-4">
        <Button
          variant="ghost"
          class="text-destructive hover:bg-destructive/10 hover:text-destructive"
          :disabled="!canDelete"
          :title="canDelete ? 'Delete dashboard' : 'You need at least one dashboard of your own'"
          data-testid="dashboard-settings-delete"
          @click="remove"
        >
          <Trash2 class="mr-1 h-4 w-4" />
          Delete
        </Button>
        <div class="flex gap-2">
          <Button
            variant="ghost"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button
            :disabled="!canSave"
            data-testid="dashboard-settings-save"
            @click="submit"
          >
            Save
          </Button>
        </div>
      </div>
    </div>
  </Dialog>
</template>
