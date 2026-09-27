<script setup lang="ts">
import type { YoloStep } from "@/features/assistant-yolo/yoloProtocol";

import ChatToolCall from "@/components/Chat/ChatToolCall.vue";

interface Props {
  steps: YoloStep[];
}

defineProps<Props>();
</script>

<template>
  <div
    class="mt-2 flex flex-col gap-1"
    data-testid="ai-assistant-yolo-steps"
  >
    <template
      v-for="step in steps"
      :key="step.id"
    >
      <ChatToolCall :tool-call="step" />
      <div
        v-if="step.children?.length || step.hiddenChildCount"
        class="ml-4 flex flex-col gap-1"
      >
        <ChatToolCall
          v-for="child in step.children"
          :key="child.id"
          :tool-call="child"
        />
        <p
          v-if="step.hiddenChildCount"
          class="px-3 text-[11px] text-muted-foreground"
        >
          +{{ step.hiddenChildCount }} more nodes
        </p>
      </div>
    </template>
  </div>
</template>
