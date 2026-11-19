<script setup lang="ts">
import { ref } from "vue";
import { Lock, LockOpen } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import { useToast } from "@/composables/useToast";
import { responseDetail } from "@/lib/responseDetail";
import { workflowApi } from "@/services/api";
import type { AllExecutionHistoryEntry } from "@/types/workflow";

interface Props {
  entryId: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "unlocked", entry: AllExecutionHistoryEntry): void;
}>();

const { showToast } = useToast();
const confirmOpen = ref(false);
const unlocking = ref(false);

async function unlock(): Promise<void> {
  unlocking.value = true;
  try {
    const entry = await workflowApi.unlockHistoryEntry(props.entryId);
    confirmOpen.value = false;
    emit("unlocked", { ...entry, unlocked: true });
  } catch (error: unknown) {
    showToast(responseDetail(error) ?? "Could not unlock this run.", "error");
  } finally {
    unlocking.value = false;
  }
}
</script>

<template>
  <div
    class="rounded-lg border border-border/60 bg-muted/30 p-4 flex flex-col sm:flex-row sm:items-center gap-3"
    data-testid="run-history-locked"
  >
    <div class="flex items-start gap-3 min-w-0 flex-1">
      <div class="shrink-0 rounded-full bg-primary/10 p-2">
        <Lock class="w-4 h-4 text-primary dark:text-violet-300" />
      </div>
      <div class="min-w-0">
        <p class="text-sm font-medium">
          Encrypted run
        </p>
        <p class="text-xs text-muted-foreground leading-relaxed mt-0.5">
          This workflow stores its run history encrypted. Inputs, outputs and node
          results stay hidden until you unlock the run.
        </p>
      </div>
    </div>
    <Button
      variant="outline"
      size="sm"
      class="shrink-0 gap-1.5"
      data-testid="run-history-unlock"
      @click="confirmOpen = true"
    >
      <LockOpen class="w-3.5 h-3.5" />
      Unlock
    </Button>
  </div>

  <Dialog
    :open="confirmOpen"
    title="Unlock this run?"
    size="sm"
    @close="confirmOpen = false"
  >
    <p class="text-sm text-muted-foreground leading-relaxed">
      The run is decrypted on the server and shown to you. Your account, the
      workflow, the run and the time are written to the audit log.
    </p>
    <div class="mt-5 flex justify-end gap-2">
      <Button
        variant="outline"
        size="sm"
        :disabled="unlocking"
        @click="confirmOpen = false"
      >
        Cancel
      </Button>
      <Button
        size="sm"
        class="gap-1.5"
        :loading="unlocking"
        data-testid="run-history-unlock-confirm"
        @click="unlock"
      >
        <LockOpen class="w-3.5 h-3.5" />
        Unlock
      </Button>
    </div>
  </Dialog>
</template>
