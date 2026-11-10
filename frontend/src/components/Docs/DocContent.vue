<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import DOMPurify from "dompurify";

import { useRoute, useRouter } from "vue-router";
import { ChevronLeft, ChevronRight } from "lucide-vue-next";

import type { NodeType } from "@/types/workflow";

import NodePreviewCard from "@/components/Docs/NodePreviewCard.vue";
import Button from "@/components/ui/Button.vue";
import { getPrevNextDoc } from "@/docs/manifest";
import { renderDocMarkdown } from "@/docs/renderMarkdown";
import { getPluginDoc } from "@/services/plugins";

interface Props {
  path: string;
}

const props = defineProps<Props>();
const router = useRouter();
const route = useRoute();
const articleRef = ref<HTMLElement | null>(null);

const prevNext = computed(() => getPrevNextDoc(props.path));

const NODE_TYPES_FOR_PREVIEW: NodeType[] = [
  "textInput",
  "cron",
  "telegramTrigger",
  "websocketTrigger",
  "llm",
  "agent",
  "condition",
  "switch",
  "output",
  "wait",
  "http",
  "websocketSend",
  "merge",
  "set",
  "telegram",
  "variable",
  "loop",
  "rag",
];

const showNodePreviews = computed(() => props.path === "reference/node-types");

const content = ref("");
const loading = ref(true);
const error = ref<string | null>(null);
let latestLoadRequestId = 0;

const docModules = import.meta.glob<string>("@/docs/content/**/*.md", {
  query: "?raw",
  import: "default",
});

function findModuleKey(path: string): string | null {
  const normalized = path.replace(/^\//, "").replace(/\/$/, "");
  const target = `${normalized}.md`;
  for (const key of Object.keys(docModules)) {
    if (key.endsWith(target) || key.includes(`/${normalized}.md`)) {
      return key;
    }
  }
  return null;
}

async function loadContent(): Promise<void> {
  const requestId = ++latestLoadRequestId;
  const requestedPath = props.path;
  loading.value = true;
  error.value = null;
  try {
    // Plugin docs are served dynamically by the backend, not bundled markdown.
    const normalized = requestedPath.replace(/^\//, "").replace(/\/$/, "");
    if (normalized.startsWith("plugins/")) {
      const pluginId = normalized.slice("plugins/".length);
      try {
        const doc = await getPluginDoc(pluginId);
        if (requestId !== latestLoadRequestId) return;
        content.value = doc.markdown || `# ${doc.name}\n\nThis plugin has no documentation.`;
      } catch {
        if (requestId !== latestLoadRequestId) return;
        content.value = "";
        error.value = "Page not found";
      }
      return;
    }

    const key = findModuleKey(requestedPath);
    const loader = key ? docModules[key] : undefined;
    if (requestId !== latestLoadRequestId) return;

    if (loader) {
      const raw = await loader();
      if (requestId !== latestLoadRequestId) return;
      content.value = typeof raw === "string" ? raw : "";
    } else {
      if (requestId !== latestLoadRequestId) return;
      content.value = "";
      error.value = "Page not found";
    }
  } catch (e) {
    if (requestId !== latestLoadRequestId) return;
    error.value = e instanceof Error ? e.message : "Failed to load content";
    content.value = "";
  } finally {
    if (requestId === latestLoadRequestId) {
      loading.value = false;
    }
  }
}

function renderMarkdown(raw: string, currentPath: string): string {
  if (!raw) return "";
  const html = renderDocMarkdown(raw, currentPath);
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      "p", "br", "strong", "em", "u", "s", "code", "pre", "blockquote",
      "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "hr",
      "table", "thead", "tbody", "tr", "th", "td", "span", "div",
      "video", "source",
    ],
    ALLOWED_ATTR: ["id", "href", "target", "rel", "class", "src", "controls", "playsinline", "muted", "loop", "preload", "type", "style"],
  });
}

const renderedHtml = computed(() => renderMarkdown(content.value, props.path));

function scrollToSection(): void {
  if (!route.hash) return;
  let id: string;
  try {
    id = decodeURIComponent(route.hash.slice(1));
  } catch {
    return;
  }
  const target = Array.from(articleRef.value?.querySelectorAll<HTMLElement>("[id]") ?? [])
    .find((element) => element.id === id);
  target?.scrollIntoView({ block: "start" });
}

async function handleContentClick(event: MouseEvent): Promise<void> {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const target = (event.target as HTMLElement).closest("a");
  const href = target?.getAttribute("href");
  if (href?.startsWith("/docs/") || href?.startsWith("#")) {
    event.preventDefault();
    await router.push(href.startsWith("#") ? { hash: href } : href);
    await nextTick();
    scrollToSection();
  }
}

watch([renderedHtml, () => route.hash], async () => {
  await nextTick();
  scrollToSection();
}, { flush: "post" });

watch(
  () => props.path,
  () => loadContent(),
  { immediate: true }
);
</script>

<template>
  <div class="doc-content">
    <div
      v-if="loading"
      class="animate-pulse text-muted-foreground"
    >
      Loading...
    </div>
    <div
      v-else-if="error"
      class="space-y-2"
    >
      <p class="text-destructive">
        {{ error }}
      </p>
      <p class="text-sm text-muted-foreground">
        Need help? Contact us at
        <a
          href="mailto:support@heym.run"
          class="text-foreground underline underline-offset-2 hover:opacity-70 transition-opacity"
        >support@heym.run</a>
      </p>
    </div>
    <div
      v-else
      class="space-y-8"
    >
      <div
        class="doc-markdown
        [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:text-foreground [&_h1]:mt-8 [&_h1]:mb-4 [&_h1]:first:mt-0
        [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-foreground [&_h2]:mt-6 [&_h2]:mb-3
        [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:text-foreground [&_h3]:mt-4 [&_h3]:mb-2
        [&_p]:text-muted-foreground [&_p]:leading-relaxed [&_p]:my-3
        [&_a]:text-primary [&_a]:no-underline hover:[&_a]:underline
        [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-sm [&_code]:font-mono
        [&_pre]:bg-muted [&_pre]:border [&_pre]:border-border [&_pre]:rounded-xl [&_pre]:p-4 [&_pre]:overflow-x-auto [&_pre]:my-4 [&_pre]:text-sm [&_pre]:font-mono
        [&_pre_code]:bg-transparent [&_pre_code]:p-0
        [&_blockquote]:border-l-4 [&_blockquote]:border-primary [&_blockquote]:bg-primary/5 [&_blockquote]:py-1 [&_blockquote]:pl-4 [&_blockquote]:pr-2 [&_blockquote]:my-4 [&_blockquote]:rounded-r-lg
        [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:my-3 [&_ul]:space-y-1
        [&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:my-3 [&_ol]:space-y-1
        [&_li]:text-muted-foreground
        [&_table]:w-full [&_table]:text-sm [&_table]:my-4
        [&_th]:text-left [&_th]:font-semibold [&_th]:p-2 [&_th]:border-b [&_th]:border-border
        [&_td]:p-2 [&_td]:border-b [&_td]:border-border/50 [&_td]:text-muted-foreground
        [&_hr]:my-6 [&_hr]:border-border
        [&_.language-dsl]:border-primary/30 [&_.language-dsl]:bg-primary/5
        [&_.github-video-link]:hidden
        [&_video]:w-full [&_video]:rounded-xl [&_video]:border [&_video]:border-border/60 [&_video]:bg-black/90 [&_video]:my-4
      "
      >
        <!-- eslint-disable vue/no-v-html -->
        <div
          ref="articleRef"
          @click="handleContentClick"
          v-html="renderedHtml"
        />
      <!-- eslint-enable vue/no-v-html -->
      </div>

      <div
        v-if="showNodePreviews"
        class="mt-12"
      >
        <h2 class="text-xl font-semibold text-foreground mb-4">
          Available Node Types
        </h2>
        <div class="flex flex-wrap gap-2">
          <NodePreviewCard
            v-for="nodeType in NODE_TYPES_FOR_PREVIEW"
            :key="nodeType"
            :node-type="nodeType"
          />
        </div>
      </div>

      <nav
        v-if="prevNext.prev || prevNext.next"
        class="flex items-center justify-between gap-4 pt-8 mt-8 border-t border-border/60"
      >
        <Button
          v-if="prevNext.prev"
          variant="outline"
          size="sm"
          class="gap-2"
          @click="router.push(prevNext.prev!.path)"
        >
          <ChevronLeft class="w-4 h-4" />
          {{ prevNext.prev!.title }}
        </Button>
        <span v-else />
        <Button
          v-if="prevNext.next"
          variant="outline"
          size="sm"
          class="gap-2"
          @click="router.push(prevNext.next!.path)"
        >
          {{ prevNext.next!.title }}
          <ChevronRight class="w-4 h-4" />
        </Button>
      </nav>
    </div>
  </div>
</template>
