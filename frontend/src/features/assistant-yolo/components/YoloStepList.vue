<script setup lang="ts">
import type { YoloStep } from "@/features/assistant-yolo/yoloProtocol";

import ChatToolCall from "@/components/Chat/ChatToolCall.vue";

interface Props {
  steps: YoloStep[];
}

const props = defineProps<Props>();

// A list that mounts with its first step is live, so that step animates in too; a reopened panel
// re-renders finished lists without replaying them.
const animateFirstStep = props.steps.length <= 1;
</script>

<template>
  <TransitionGroup
    tag="div"
    name="yolo-step"
    class="mt-2 flex flex-col gap-1"
    data-testid="ai-assistant-yolo-steps"
    :appear="animateFirstStep"
  >
    <div
      v-for="step in steps"
      :key="step.id"
      class="flex flex-col gap-1"
    >
      <div :class="step.status === 'running' && 'yolo-step-running'">
        <ChatToolCall :tool-call="step" />
      </div>
      <TransitionGroup
        v-if="step.children?.length || step.hiddenChildCount"
        tag="div"
        name="yolo-step"
        class="ml-4 flex flex-col gap-1"
      >
        <div
          v-for="child in step.children"
          :key="child.id"
          :class="child.status === 'running' && 'yolo-step-running'"
        >
          <ChatToolCall :tool-call="child" />
        </div>
        <p
          v-if="step.hiddenChildCount"
          key="hidden-children"
          class="px-3 text-[11px] text-muted-foreground"
        >
          +{{ step.hiddenChildCount }} more nodes
        </p>
      </TransitionGroup>
    </div>
  </TransitionGroup>
</template>

<style scoped>
.yolo-step-running :deep(.chat-tool-call-label) {
  background: linear-gradient(
    90deg,
    hsl(var(--muted-foreground)) 0%,
    hsl(var(--muted-foreground)) 35%,
    hsl(var(--foreground)) 50%,
    hsl(var(--muted-foreground)) 65%,
    hsl(var(--muted-foreground)) 100%
  );
  background-size: 250% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: yolo-step-shimmer 1.8s linear infinite;
}

/* Vue times the enter by this element's own transition, so it covers the label reveal below. */
.yolo-step-enter-active {
  transition:
    opacity 280ms ease-out,
    transform 450ms cubic-bezier(0.16, 1, 0.3, 1);
}

.yolo-step-enter-from {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}

.yolo-step-move {
  transition: transform 300ms cubic-bezier(0.16, 1, 0.3, 1);
}

.yolo-step-enter-active :deep(.chat-tool-call-label) {
  animation: yolo-step-type 450ms steps(18, end) both;
}

@keyframes yolo-step-type {
  from {
    clip-path: inset(0 100% 0 0);
  }
  to {
    clip-path: inset(0 0 0 0);
  }
}

@keyframes yolo-step-shimmer {
  from {
    background-position: 100% 0;
  }
  to {
    background-position: -150% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .yolo-step-enter-active,
  .yolo-step-move {
    transition: none;
  }

  .yolo-step-enter-active :deep(.chat-tool-call-label),
  .yolo-step-running :deep(.chat-tool-call-label) {
    animation: none;
  }
}
</style>
