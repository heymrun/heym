<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watchEffect } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ChevronRight, History, Send, SquarePen } from "lucide-vue-next";

import type { WorkflowListItem } from "@/types/workflow";
import AppHeader from "@/components/Layout/AppHeader.vue";
import DashboardNav from "@/components/Layout/DashboardNav.vue";
import WorkspaceShell from "@/components/Layout/WorkspaceShell.vue";
import ChatListPanel from "@/components/Chat/ChatListPanel.vue";
import ChatConversation from "@/components/Chat/ChatConversation.vue";
import WorkflowCommandPalette from "@/components/Dialogs/WorkflowCommandPalette.vue";
import ExecutionHistoryAllDialog from "@/components/Panels/ExecutionHistoryAllDialog.vue";
import Button from "@/components/ui/Button.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { getDocPath } from "@/docs/manifest";
import ReleaseTourHost from "@/features/release-tour/components/ReleaseTourHost.vue";
import type { ShowcaseContext } from "@/features/showcase/showcase.types";
import { hasShowcaseChatDraftPending } from "@/features/showcase/showcaseChatDraft";
import { joinOriginAndPath } from "@/lib/appUrl";
import { isPaletteOpenInNewTab } from "@/lib/paletteNavigate";
import { useRecentWorkflows } from "@/composables/useRecentWorkflows";
import { workflowApi } from "@/services/api";
import { useChatStore } from "@/stores/chat";

const chatsShowcaseContext: ShowcaseContext = "dashboard:chat";
const MOBILE_SIDEBAR_MEDIA_QUERY = "(max-width: 767px)";
const DEFAULT_APP_TITLE = "Heym - AI Agent Runtime";

const route = useRoute();
const router = useRouter();
const chatStore = useChatStore();
const { addRecent } = useRecentWorkflows();

const conversationId = computed(() => route.params.id as string | undefined);
const isCreatingConversation = ref(false);
const isMobileViewport = ref(false);
const showCommandPalette = ref(false);
const historyOpen = ref(false);
const releaseTourEligible = computed(() => !showCommandPalette.value && !historyOpen.value);
const workflows = ref<WorkflowListItem[]>([]);
const previousDocumentTitle = ref(DEFAULT_APP_TITLE);
let mobileSidebarMediaQuery: MediaQueryList | null = null;

async function createNew(): Promise<void> {
  if (isCreatingConversation.value) return;
  isCreatingConversation.value = true;
  try {
    const conv = await chatStore.createConversation();
    await router.push(`/chats/${conv.id}`);
  } finally {
    isCreatingConversation.value = false;
  }
}

function syncMobileSidebarState(): void {
  isMobileViewport.value = mobileSidebarMediaQuery?.matches ?? false;
  if (isMobileViewport.value) {
    chatStore.closeSidebar();
  } else {
    chatStore.openSidebar();
  }
}

function handleKeyDown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    showCommandPalette.value = true;
    pushOverlayState();
  }
}

async function loadWorkflows(): Promise<void> {
  try {
    workflows.value = await workflowApi.list();
  } catch {
    workflows.value = [];
  }
}

function openWorkflowFromPalette(workflowId: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const workflow = workflows.value.find((w) => w.id === workflowId);
  if (workflow) {
    addRecent(workflowId, workflow.name);
  }
  const resolved = router.resolve({ name: "editor", params: { id: workflowId } });
  if (isPaletteOpenInNewTab(event)) {
    window.open(resolved.href, "_blank", "noopener,noreferrer");
  } else {
    router.push({ name: "editor", params: { id: workflowId } });
  }
}

function handleTabSelectFromPalette(tabId: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const openInNewTab = isPaletteOpenInNewTab(event);
  const path = tabId === "evals"
    ? "/evals"
    : tabId === "chat"
      ? "/chats"
      : tabId === "workflows"
        ? "/"
        : `/?tab=${tabId}`;
  if (openInNewTab) {
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
  } else if (tabId === "evals" || tabId === "chat" || tabId === "workflows") {
    router.push(path);
  } else {
    router.push({ path: "/", query: { tab: tabId } });
  }
}

function onDocSelectFromPalette(categoryId: string, slug: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const path = getDocPath(categoryId, slug);
  if (isPaletteOpenInNewTab(event)) {
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
  } else {
    router.push(path);
  }
}

onMounted(() => {
  if (typeof window !== "undefined") {
    previousDocumentTitle.value = document.title.includes("Heym Chat Assistant")
      ? DEFAULT_APP_TITLE
      : document.title;
    mobileSidebarMediaQuery = window.matchMedia(MOBILE_SIDEBAR_MEDIA_QUERY);
    syncMobileSidebarState();
    mobileSidebarMediaQuery.addEventListener("change", syncMobileSidebarState);
    window.addEventListener("keydown", handleKeyDown);
  }
  void loadWorkflows();
  const unsub = onDismissOverlays(() => {
    showCommandPalette.value = false;
    historyOpen.value = false;
  });
  onUnmounted(() => unsub());
  if (!conversationId.value && hasShowcaseChatDraftPending()) {
    void createNew();
  }
});

watchEffect(() => {
  const count = chatStore.conversations.filter((c) => c.has_unread).length;
  document.title = count > 0 ? `(${count}) Heym Chat Assistant` : "Heym Chat Assistant";
});

onUnmounted(() => {
  document.title = previousDocumentTitle.value;
  mobileSidebarMediaQuery?.removeEventListener("change", syncMobileSidebarState);
  if (typeof window !== "undefined") {
    window.removeEventListener("keydown", handleKeyDown);
  }
});
</script>

<template>
  <WorkspaceShell :showcase-context="chatsShowcaseContext">
    <div class="h-screen flex flex-col bg-background overflow-hidden">
      <AppHeader :on-open-command-palette="() => { showCommandPalette = true; pushOverlayState(); }">
        <template #before-docs>
          <div
            id="release-tour-launcher-slot"
            class="contents"
          />
          <button
            v-if="isMobileViewport && !chatStore.isSidebarOpen"
            class="p-2 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title="Open chat list"
            @click="chatStore.toggleSidebar"
          >
            <ChevronRight class="w-4 h-4" />
          </button>
        </template>
        <template #actions>
          <Button
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

      <main class="dashboard-main flex-1 flex flex-col min-h-0 overflow-hidden px-3 sm:px-4 py-4 sm:py-6 md:py-8">
        <div class="absolute top-0 left-0 right-0 h-[500px] pointer-events-none overflow-hidden">
          <div class="absolute inset-0 bg-gradient-to-b from-primary/[0.03] via-transparent to-transparent" />
          <div class="absolute inset-0 bg-dots-pattern opacity-30" />
        </div>

        <div class="w-full max-w-7xl mx-auto relative flex-1 flex flex-col min-h-0">
          <DashboardNav />

          <div class="relative flex flex-1 min-h-0 rounded-2xl border border-border/50 bg-card/60 overflow-hidden shadow-sm">
            <div
              v-if="!chatStore.isSidebarOpen && !isMobileViewport"
              class="absolute left-0 top-0 z-20 h-full w-6"
              aria-hidden="true"
              @mouseenter="chatStore.openSidebar"
            />

            <div
              v-if="isMobileViewport && chatStore.isSidebarOpen"
              class="absolute inset-0 z-10"
              aria-hidden="true"
              @click="chatStore.closeSidebar()"
            />

            <div
              class="chat-sidebar-shell"
              :class="{
                'chat-sidebar-shell--closed': !chatStore.isSidebarOpen,
                'relative z-20': isMobileViewport && chatStore.isSidebarOpen,
              }"
              :aria-hidden="!chatStore.isSidebarOpen"
            >
              <ChatListPanel
                class="chat-sidebar-panel"
                :class="{ 'chat-sidebar-panel--closed': !chatStore.isSidebarOpen }"
                :active-conversation-id="conversationId"
              />
            </div>

            <div class="flex-1 flex flex-col min-w-0 h-full">
              <ChatConversation
                v-if="conversationId"
                :conversation-id="conversationId"
              />

              <div
                v-else
                class="flex-1 flex flex-col items-center justify-center gap-4 text-muted-foreground"
              >
                <Send class="w-10 h-10 sm:w-12 sm:h-12 opacity-50" />
                <p class="text-xs sm:text-sm max-w-[280px] sm:max-w-none text-center">
                  Ask to run a workflow, list workflows, or ask about your data.
                </p>
                <button
                  class="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50 transition-colors"
                  :disabled="isCreatingConversation"
                  @click="createNew"
                >
                  <SquarePen class="w-4 h-4" />
                  New Chat
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      <WorkflowCommandPalette
        :open="showCommandPalette"
        :workflows="workflows"
        context="dashboard"
        active-tab="chat"
        @select="openWorkflowFromPalette"
        @tab-select="handleTabSelectFromPalette"
        @doc-select="onDocSelectFromPalette"
        @close="showCommandPalette = false"
      />

      <ExecutionHistoryAllDialog
        :open="historyOpen"
        @close="historyOpen = false"
      />

      <ReleaseTourHost :eligible="releaseTourEligible" />
    </div>
  </WorkspaceShell>
</template>

<style scoped>
.chat-sidebar-shell {
  width: 16rem;
  overflow: hidden;
  flex-shrink: 0;
  transition: width 240ms cubic-bezier(0.22, 1, 0.36, 1);
  will-change: width;
}

.chat-sidebar-shell--closed {
  width: 0;
}

.chat-sidebar-panel {
  transform: translate3d(0, 0, 0);
  opacity: 1;
  transition:
    transform 240ms cubic-bezier(0.22, 1, 0.36, 1),
    opacity 160ms ease-out;
  will-change: transform, opacity;
}

.chat-sidebar-panel--closed {
  pointer-events: none;
  transform: translate3d(-18px, 0, 0);
  opacity: 0;
}
</style>
