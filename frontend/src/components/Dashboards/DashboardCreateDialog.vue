<script setup lang="ts">
import { computed, ref } from "vue";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { useDashboardStore } from "@/stores/dashboard";

defineProps<{ open: boolean }>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "created", dashboardId: string): void;
}>();

const dashboardStore = useDashboardStore();
const name = ref("");
const saving = ref(false);
const canCreate = computed<boolean>(() => Boolean(name.value.trim()) && !saving.value);

async function submit(): Promise<void> {
  if (!canCreate.value) return;
  saving.value = true;
  try {
    const dashboard = await dashboardStore.createDashboard(name.value.trim());
    name.value = "";
    emit("created", dashboard.id);
    emit("close");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="open"
    title="New dashboard"
    size="sm"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-1">
      <Input
        v-model="name"
        placeholder="Dashboard name"
        data-testid="dashboard-create-name"
        @keydown.enter="submit"
      />
      <div class="flex justify-end gap-2">
        <Button
          variant="ghost"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          :disabled="!canCreate"
          data-testid="dashboard-create-submit"
          @click="submit"
        >
          Create dashboard
        </Button>
      </div>
    </div>
  </Dialog>
</template>
