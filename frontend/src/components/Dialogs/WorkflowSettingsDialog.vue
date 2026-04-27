<script setup lang="ts">
import { ref, watch } from "vue";
import { Settings } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

const workflowStore = useWorkflowStore();

const isOpen = ref(false);
const isSaving = ref(false);
const name = ref("");
const description = ref("");

watch(
  () => isOpen.value,
  (open) => {
    if (open && workflowStore.currentWorkflow) {
      name.value = workflowStore.currentWorkflow.name;
      description.value = workflowStore.currentWorkflow.description || "";
    }
  }
);

function openDialog(): void {
  isOpen.value = true;
}

function closeDialog(): void {
  isOpen.value = false;
}

async function handleSave(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  if (!name.value.trim()) return;

  isSaving.value = true;
  try {
    const updated = await workflowApi.update(workflowStore.currentWorkflow.id, {
      name: name.value.trim(),
      description: description.value.trim() || null,
    });
    workflowStore.currentWorkflow.name = updated.name;
    workflowStore.currentWorkflow.description = updated.description;
    closeDialog();
  } finally {
    isSaving.value = false;
  }
}

defineExpose({ openDialog });
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed inset-0 z-50 flex items-center justify-center"
    >
      <div
        class="absolute inset-0 bg-background/80 backdrop-blur-sm"
        @click="closeDialog"
      />

      <div class="relative bg-card border rounded-lg shadow-lg w-full max-w-md p-6 animate-in fade-in zoom-in-95">
        <div class="flex items-center gap-3 mb-6">
          <div class="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10">
            <Settings class="w-5 h-5 text-primary" />
          </div>
          <div>
            <h2 class="text-lg font-semibold">
              Workflow Settings
            </h2>
            <p class="text-sm text-muted-foreground">
              Edit workflow name and description
            </p>
          </div>
        </div>

        <div class="space-y-4">
          <div class="space-y-2">
            <Label for="workflow-name">
              Name
            </Label>
            <Input
              id="workflow-name"
              v-model="name"
              placeholder="Workflow name"
              @keydown.enter="handleSave"
            />
          </div>

          <div class="space-y-2">
            <Label for="workflow-description">
              Description
            </Label>
            <Textarea
              id="workflow-description"
              v-model="description"
              placeholder="Optional description..."
              :rows="3"
            />
          </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <Button
            variant="outline"
            @click="closeDialog"
          >
            Cancel
          </Button>
          <Button
            :loading="isSaving"
            :disabled="!name.trim()"
            @click="handleSave"
          >
            Save Changes
          </Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>