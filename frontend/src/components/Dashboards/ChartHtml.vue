<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { buildHtmlWidgetDocument, HTML_WIDGET_SANDBOX, htmlWidgetLink } from "@/lib/htmlWidgetDocument";

const props = defineProps<{ html: string; dark: boolean; title?: string }>();

const frame = ref<HTMLIFrameElement | null>(null);
const srcdoc = computed((): string => buildHtmlWidgetDocument(props.html, props.dark));

// Only this widget's own frame may ask for a link, and only an http(s) or in-app one opens.
function onMessage(event: MessageEvent): void {
  if (!frame.value || event.source !== frame.value.contentWindow) return;
  const href = htmlWidgetLink(event.data);
  if (href) window.open(href, "_blank", "noopener,noreferrer");
}

onMounted(() => window.addEventListener("message", onMessage));
onBeforeUnmount(() => window.removeEventListener("message", onMessage));
</script>

<template>
  <iframe
    ref="frame"
    class="block h-full min-h-[120px] w-full border-0 bg-transparent"
    :style="{ colorScheme: dark ? 'dark' : 'light' }"
    :sandbox="HTML_WIDGET_SANDBOX"
    :srcdoc="srcdoc"
    :title="title || 'HTML widget'"
    referrerpolicy="no-referrer"
    data-testid="chart-html-frame"
  />
</template>
