<script setup lang="ts">
import { computed } from "vue";
import { LockOpen } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import { useWorkflowStore } from "@/stores/workflow";

/** Asks before the canvas attaches to a running run of an encrypted workflow. */
const workflowStore = useWorkflowStore();
const open = computed(() => workflowStore.lockedLiveExecutionId !== null);
const live = computed(() => workflowStore.lockedRunKind === "live");
</script>

<template>
  <Dialog
    :open="open"
    :title="live ? 'Watch this encrypted run?' : 'Open this encrypted run?'"
    size="sm"
    @close="workflowStore.dismissLockedLiveExecution()"
  >
    <p class="text-sm text-muted-foreground leading-relaxed">
      This workflow stores its runs encrypted. {{ live ? "Watching it live" : "Opening it" }}
      shows its inputs and node results, and your account, the run and the time are
      written to the audit log.
    </p>
    <div class="mt-5 flex justify-end gap-2">
      <Button
        variant="outline"
        size="sm"
        @click="workflowStore.dismissLockedLiveExecution()"
      >
        Cancel
      </Button>
      <Button
        size="sm"
        class="gap-1.5"
        data-testid="live-run-unlock-confirm"
        @click="workflowStore.unlockLiveExecution()"
      >
        <LockOpen class="w-3.5 h-3.5" />
        {{ live ? "Unlock and watch" : "Unlock and open" }}
      </Button>
    </div>
  </Dialog>
</template>
