<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { Sparkles } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import { saveChatContextDraft } from "@/lib/chatContext";

interface Props {
  workflowId: string | null | undefined;
  workflowName: string;
  /** Execution history row id of the selected run. */
  executionId: string | null | undefined;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  /** Fired before navigating, so the history dialog can close itself. */
  navigate: [];
}>();

const router = useRouter();

const canAsk = computed<boolean>(() => Boolean(props.workflowId && props.executionId));

/** Open the Chat tab with the workflow and the run attached as context chips. */
function askAi(): void {
  const { workflowId, workflowName, executionId } = props;
  if (!workflowId || !executionId) return;
  saveChatContextDraft([
    { kind: "workflow", workflowId, workflowName },
    { kind: "execution", workflowId, executionId },
  ]);
  emit("navigate");
  void router.push("/chats");
}
</script>

<template>
  <Button
    variant="outline"
    size="sm"
    class="!h-7 !min-h-7 !rounded-lg !px-2.5 gap-1 text-xs"
    :disabled="!canAsk"
    title="Ask the Chat assistant about this run"
    data-testid="execution-history-ask-ai"
    @click="askAi"
  >
    <Sparkles class="w-3.5 h-3.5" />
    Ask AI
  </Button>
</template>
