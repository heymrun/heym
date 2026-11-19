<script setup lang="ts">
import { computed, ref } from "vue";
import { Lock } from "lucide-vue-next";

import { useToast } from "@/composables/useToast";
import { responseDetail } from "@/lib/responseDetail";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

interface Props {
  isOwner: boolean;
}

const props = defineProps<Props>();

const workflowStore = useWorkflowStore();
const { showToast } = useToast();
const saving = ref(false);

const enabled = computed(() => workflowStore.currentWorkflow?.encrypt_run_history ?? false);

async function toggle(): Promise<void> {
  const wf = workflowStore.currentWorkflow;
  if (!wf || !props.isOwner || saving.value) return;
  const next = !enabled.value;
  saving.value = true;
  try {
    const response = await workflowApi.setRunHistoryEncryption(wf.id, next);
    wf.encrypt_run_history = response.encrypt_run_history;
    showToast(
      next
        ? "Run history encryption is on for new runs."
        : "Run history encryption is off for new runs. Earlier runs stay encrypted.",
    );
  } catch (error: unknown) {
    showToast(responseDetail(error) ?? "Could not change run history encryption.", "error");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div
    class="border-t border-border/40 pt-4 pb-4"
    data-testid="workflow-run-history-encryption"
  >
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2 min-w-0">
        <Lock class="w-4 h-4 text-muted-foreground shrink-0" />
        <span class="text-sm font-medium">Encrypt run history</span>
      </div>
      <button
        type="button"
        role="switch"
        aria-label="Encrypt run history"
        data-testid="workflow-run-history-encryption-toggle"
        :aria-checked="enabled"
        :disabled="!isOwner || saving"
        class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :class="enabled ? 'bg-primary' : 'bg-muted-foreground/30'"
        @click="toggle"
      >
        <span
          class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
          :class="enabled ? 'translate-x-4' : 'translate-x-0.5'"
        />
      </button>
    </div>
    <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
      New runs, test runs included, are stored encrypted. Viewing one takes an
      audited unlock, for owners and admins too.
    </p>
  </div>
</template>
