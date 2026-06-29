<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useMediaQuery } from "@vueuse/core";
import { History, Menu, Wand2 } from "lucide-vue-next";
import { useRoute, useRouter } from "vue-router";
import type { WorkflowListItem } from "@/types/workflow";

import DocsChatDialog from "@/components/Docs/DocsChatDialog.vue";
import DocContent from "@/components/Docs/DocContent.vue";
import GitHubStarButton from "@/components/Docs/GitHubStarButton.vue";
import DocsMobileDrawer from "@/components/Docs/DocsMobileDrawer.vue";
import DocsSidebar from "@/components/Docs/DocsSidebar.vue";
import WorkflowCommandPalette from "@/components/Dialogs/WorkflowCommandPalette.vue";
import AppHeader from "@/components/Layout/AppHeader.vue";
import ExecutionHistoryAllDialog from "@/components/Panels/ExecutionHistoryAllDialog.vue";
import WorkspaceShell from "@/components/Layout/WorkspaceShell.vue";
import Button from "@/components/ui/Button.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { getDocPath, type DocCategory } from "@/docs/manifest";
import { listPlugins } from "@/services/plugins";
import { joinOriginAndPath } from "@/lib/appUrl";
import { isPaletteOpenInNewTab } from "@/lib/paletteNavigate";
import { resolveShowcaseContext } from "@/features/showcase/showcaseResolver";
import { workflowApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

const isMobile = useMediaQuery("(max-width: 767px)");
const authStore = useAuthStore();
const showCommandPalette = ref(false);
const historyOpen = ref(false);
const mobileDrawerOpen = ref(false);
const docsChatOpen = ref(false);
const workflows = ref<WorkflowListItem[]>([]);

const route = useRoute();
const router = useRouter();
const showcaseContext = computed(() => {
  return resolveShowcaseContext({ routePath: route.path });
});

const pluginCategories = ref<Record<string, DocCategory>>({});

async function loadPluginDocs(): Promise<void> {
  try {
    const plugins = (await listPlugins()).filter((plugin) => plugin.enabled);
    if (plugins.length === 0) {
      pluginCategories.value = {};
      return;
    }
    pluginCategories.value = {
      plugins: {
        id: "plugins",
        label: "Plugins",
        items: plugins.map((plugin) => ({ slug: plugin.id, title: plugin.name })),
      },
    };
  } catch {
    pluginCategories.value = {};
  }
}

function handleKeyDown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key === "k") {
    event.preventDefault();
    showCommandPalette.value = true;
    pushOverlayState();
  }
}

onMounted(async () => {
  window.addEventListener("keydown", handleKeyDown);
  const unsub = onDismissOverlays(() => {
    showCommandPalette.value = false;
    historyOpen.value = false;
    mobileDrawerOpen.value = false;
    docsChatOpen.value = false;
  });
  onUnmounted(() => unsub());
  await authStore.fetchUser();
  try {
    workflows.value = await workflowApi.list();
  } catch {
    workflows.value = [];
  }
  void loadPluginDocs();
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeyDown);
});

const docPath = computed(() => {
  const pathMatch = route.params.pathMatch;
  if (pathMatch == null || pathMatch === "") return null;
  let path = Array.isArray(pathMatch) ? pathMatch.join("/") : String(pathMatch);
  path = path.trim();
  if (path.endsWith(".md")) path = path.slice(0, -3);
  return path || null;
});

const contentScrollRef = ref<HTMLElement | null>(null);

watch(docPath, async () => {
  await nextTick();
  contentScrollRef.value?.scrollTo({ top: 0, behavior: "auto" });
});

function onPaletteSelect(workflowId: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  if (isPaletteOpenInNewTab(event)) {
    const resolved = router.resolve({ name: "editor", params: { id: workflowId } });
    window.open(resolved.href, "_blank", "noopener,noreferrer");
  } else {
    router.push({ name: "editor", params: { id: workflowId } });
  }
}

function onPaletteTabSelect(tabId: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const openInNewTab = isPaletteOpenInNewTab(event);
  if (openInNewTab) {
    const path =
      tabId === "evals"
        ? "/evals"
        : tabId === "chat"
          ? "/chats"
          : tabId === "workflows"
            ? "/"
            : `/?tab=${tabId}`;
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
  } else if (tabId === "evals") {
    router.push("/evals");
  } else if (tabId === "chat") {
    router.push("/chats");
  } else if (tabId === "workflows") {
    router.push("/");
  } else {
    router.push({ path: "/", query: { tab: tabId } });
  }
}

function onDocSelect(categoryId: string, slug: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const path = getDocPath(categoryId, slug);
  if (isPaletteOpenInNewTab(event)) {
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
  } else {
    router.push(path);
  }
}
</script>

<template>
  <WorkspaceShell :showcase-context="showcaseContext">
    <div class="h-screen bg-background flex flex-col overflow-hidden">
      <AppHeader
        hide-docs-link
        :on-open-command-palette="() => { showCommandPalette = true; pushOverlayState(); }"
      >
        <template #left-actions>
          <Button
            variant="ghost"
            size="icon"
            class="md:hidden h-11 w-11 min-h-[44px] min-w-[44px] text-foreground"
            title="Open documentation menu"
            aria-label="Open documentation menu"
            @click="mobileDrawerOpen = true; pushOverlayState()"
          >
            <Menu class="w-5 h-5" />
          </Button>
        </template>
        <template #actions>
          <button
            type="button"
            class="inline-flex items-center justify-center gap-1.5 rounded-xl bg-purple-600 px-3 text-sm font-medium text-white transition-all duration-250 hover:bg-purple-700 active:scale-[0.97] min-h-[44px] min-w-[44px] md:h-9 md:min-h-[36px]"
            title="Chat with Docs"
            aria-label="Chat with Docs"
            @click="docsChatOpen = true; pushOverlayState()"
          >
            <Wand2 class="h-4 w-4 shrink-0" />
            <span class="hidden sm:inline text-xs font-medium">Chat with Docs</span>
          </button>
          <GitHubStarButton />
          <Button
            v-if="authStore.user"
            variant="ghost"
            size="sm"
            class="gap-2 min-h-[44px] min-w-[44px] sm:min-w-auto text-foreground"
            @click="historyOpen = true; pushOverlayState()"
          >
            <History class="w-4 h-4" />
            <span class="hidden sm:inline">History</span>
          </Button>
        </template>
      </AppHeader>

      <main class="flex-1 flex min-h-0 overflow-hidden relative">
        <DocsMobileDrawer
          :open="mobileDrawerOpen"
          :extra-categories="pluginCategories"
          @update:open="mobileDrawerOpen = $event"
        />
        <DocsSidebar
          class="hidden md:flex"
          :extra-categories="pluginCategories"
        />

        <div
          ref="contentScrollRef"
          class="flex-1 min-w-0 min-h-0 overflow-y-auto overflow-x-hidden px-4 py-6 md:px-6 md:py-8"
        >
          <div class="max-w-3xl mx-auto">
            <DocContent
              v-if="docPath"
              :path="docPath"
            />
            <div v-else>
              <h1 class="text-2xl font-bold text-foreground">
                Documentation
              </h1>
              <p class="mt-2 text-muted-foreground">
                Welcome to Heym.
                <template v-if="isMobile">
                  Use the menu above to browse topics.
                </template>
                <template v-else>
                  Select a topic from the sidebar.
                </template>
              </p>
              <p class="mt-4 text-sm text-muted-foreground">
                Need help? Reach us at
                <a
                  href="mailto:support@heym.run"
                  class="text-foreground underline underline-offset-2 hover:opacity-70 transition-opacity"
                >support@heym.run</a>
              </p>
            </div>
          </div>
        </div>
      </main>

      <WorkflowCommandPalette
        :open="showCommandPalette"
        :workflows="workflows"
        context="dashboard"
        @select="onPaletteSelect"
        @tab-select="onPaletteTabSelect"
        @doc-select="onDocSelect"
        @close="showCommandPalette = false"
      />

      <ExecutionHistoryAllDialog
        :open="historyOpen"
        @close="historyOpen = false"
      />

      <DocsChatDialog
        :open="docsChatOpen"
        :doc-path="docPath"
        @close="docsChatOpen = false"
      />
    </div>
  </WorkspaceShell>
</template>
