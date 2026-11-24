<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import type { RunWidgetAction } from "@/types/dashboard";
import {
  buildHtmlWidgetDocument,
  HTML_WIDGET_ACTION_RESULT,
  HTML_WIDGET_SANDBOX,
  htmlWidgetAction,
  htmlWidgetLink,
} from "@/lib/htmlWidgetDocument";

const props = defineProps<{
  html: string;
  dark: boolean;
  title?: string;
  actionNodeId?: string;
  runAction?: RunWidgetAction;
}>();

const frame = ref<HTMLIFrameElement | null>(null);
const actionRunning = ref(false);
const actionError = ref<string | null>(null);
const widgetDocument = computed(() => {
  const channel = props.actionNodeId && props.runAction
    ? crypto.getRandomValues(new Uint32Array(4)).join("-")
    : undefined;
  return { channel, srcdoc: buildHtmlWidgetDocument(props.html, props.dark, channel) };
});

async function onMessage(event: MessageEvent): Promise<void> {
  const source = frame.value?.contentWindow;
  if (!source || event.source !== source || event.origin !== "null") return;
  const href = htmlWidgetLink(event.data);
  if (href) {
    window.open(href, "_blank", "noopener,noreferrer");
    return;
  }
  const { channel } = widgetDocument.value;
  if (!channel || !props.actionNodeId || !props.runAction) return;
  const action = htmlWidgetAction(event.data, channel);
  if (!action) return;
  let error: string | null = null;
  if (!action.event || actionRunning.value) {
    error = actionRunning.value ? "A widget action is already running" : "Invalid widget action";
  } else {
    actionError.value = null;
    actionRunning.value = true;
    try {
      await props.runAction(props.actionNodeId, action.event);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : "Widget action failed";
      actionError.value = error;
    } finally {
      actionRunning.value = false;
    }
  }
  if (widgetDocument.value.channel === channel) {
    source.postMessage({ type: HTML_WIDGET_ACTION_RESULT, channel, id: action.id, error }, "*");
  }
}

onMounted(() => window.addEventListener("message", onMessage));
onBeforeUnmount(() => window.removeEventListener("message", onMessage));
</script>

<template>
  <div
    class="flex h-full min-h-0 flex-col"
    :aria-busy="actionRunning"
  >
    <iframe
      ref="frame"
      class="block h-full min-h-[120px] w-full flex-1 border-0 bg-transparent"
      :style="{ colorScheme: dark ? 'dark' : 'light' }"
      :sandbox="HTML_WIDGET_SANDBOX"
      :srcdoc="widgetDocument.srcdoc"
      :title="title || 'HTML widget'"
      referrerpolicy="no-referrer"
      data-testid="chart-html-frame"
    />
    <p
      v-if="actionError"
      role="alert"
      class="max-h-20 overflow-auto px-2 pb-1 text-xs text-destructive"
    >
      {{ actionError }}
    </p>
  </div>
</template>
