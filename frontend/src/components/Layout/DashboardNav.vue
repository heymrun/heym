<script setup lang="ts">
import { computed, ref, watch, nextTick, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Activity,
  BarChart3,
  CalendarClock,
  Database,
  FlaskConical,
  HardDrive,
  Key,
  LayoutTemplate,
  MessageCircle,
  Server,
  Table2,
  Terminal,
  Users,
  Variable,
  Workflow,
} from "lucide-vue-next";

import { cn } from "@/lib/utils";

const router = useRouter();
const route = useRoute();

const tabs = [
  { id: "workflows", label: "Workflows", icon: Workflow },
  { id: "schedules", label: "Scheduled", icon: CalendarClock },
  { id: "templates", label: "Templates", icon: LayoutTemplate },
  { id: "globalvariables", label: "Variables", icon: Variable },
  { id: "chat", label: "Chat", icon: MessageCircle },
  { id: "drive", label: "Drive", icon: HardDrive },
  { id: "datatable", label: "DataTable", icon: Table2 },
  { id: "credentials", label: "Credentials", icon: Key },
  { id: "vectorstores", label: "Vectors", icon: Database },
  { id: "mcp", label: "MCP", icon: Server },
  { id: "traces", label: "Traces", icon: Activity },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "evals", label: "Evals", icon: FlaskConical },
  { id: "teams", label: "Teams", icon: Users },
  { id: "logs", label: "Logs", icon: Terminal },
] as const;

const activeTab = computed(() => {
  if (route.path === "/evals") return "evals";
  const tabParam = route.query.tab as string;
  if (
    tabParam === "schedules" ||
    tabParam === "credentials" ||
    tabParam === "globalvariables" ||
    tabParam === "vectorstores" ||
    tabParam === "mcp" ||
    tabParam === "traces" ||
    tabParam === "analytics" ||
    tabParam === "logs" ||
    tabParam === "chat" ||
    tabParam === "drive" ||
    tabParam === "datatable" ||
    tabParam === "templates" ||
    tabParam === "teams"
  ) {
    return tabParam;
  }
  if (tabParam?.startsWith("datatable/")) {
    return "datatable";
  }
  return "workflows";
});

function getTabHref(tabId: (typeof tabs)[number]["id"]): string {
  if (tabId === "evals") return "/evals";
  if (tabId === "workflows") return "/";
  return `/?tab=${tabId}`;
}

function goToTab(tabId: (typeof tabs)[number]["id"], event?: MouseEvent): void {
  const openInNewTab = event && (event.ctrlKey || event.metaKey);
  const href = getTabHref(tabId);

  if (openInNewTab) {
    const fullUrl = new URL(href, window.location.origin).href;
    window.open(fullUrl, "_blank", "noopener,noreferrer");
    return;
  }

  if (tabId === "evals") {
    router.push("/evals");
    return;
  }
  if (tabId === "workflows") {
    router.push("/");
    return;
  }
  router.push({ path: "/", query: { tab: tabId } });
}

const tabContainerRef = ref<HTMLElement | null>(null);

function isTabFullyVisible(container: HTMLElement, tabEl: HTMLElement): boolean {
  const containerRect = container.getBoundingClientRect();
  const tabRect = tabEl.getBoundingClientRect();
  const padding = 4;
  return (
    tabRect.left >= containerRect.left + padding &&
    tabRect.right <= containerRect.right - padding
  );
}

const TAB_ANIM_KEY = "dashboardNav:tabScrollAnimPlayed";

onMounted(() => {
  nextTick(() => {
    const container = tabContainerRef.value;
    if (!container) return;

    if (container.scrollWidth <= container.clientWidth + 4) return;

    if (sessionStorage.getItem(TAB_ANIM_KEY)) return;
    sessionStorage.setItem(TAB_ANIM_KEY, "1");

    const originalScrollLeft = container.scrollLeft;
    const maxScrollLeft = container.scrollWidth - container.clientWidth;
    const targetScrollLeft = maxScrollLeft > 0 ? maxScrollLeft : originalScrollLeft + 60;

    container.scrollTo({ left: targetScrollLeft, behavior: "smooth" });

    window.setTimeout(() => {
      if (!tabContainerRef.value) return;
      tabContainerRef.value.scrollTo({ left: originalScrollLeft, behavior: "smooth" });
    }, 450);
  });
});

watch(activeTab, () => {
  nextTick(() => {
    const container = tabContainerRef.value;
    if (!container) return;
    const activeEl = container.querySelector<HTMLElement>(
      `[data-tab-id="${activeTab.value}"]`,
    );
    if (!activeEl) return;
    if (isTabFullyVisible(container, activeEl)) return;
    activeEl.scrollIntoView({ block: "nearest", inline: "center", behavior: "auto" });
  });
}, { immediate: true });
</script>

<template>
  <div
    ref="tabContainerRef"
    :class="cn(
      'tab-container flex items-center gap-5 p-2 sm:p-2.5 rounded-2xl bg-card/60 border border-border/50 overflow-x-auto backdrop-blur-md shadow-sm scrollbar-thin w-full shrink-0',
      activeTab === 'chat' ? 'mb-3 sm:mb-4' : 'mb-5'
    )"
  >
    <button
      v-for="tab in tabs"
      :key="tab.id"
      :data-tab-id="tab.id"
      :title="`${tab.label} (Ctrl+click to open in new tab)`"
      :class="cn(
        'tab-item flex shrink-0 items-center justify-center gap-1.5 px-2 sm:px-2.5 py-1.5 min-h-[36px] rounded-lg text-sm font-medium transition-all duration-250 whitespace-nowrap',
        activeTab === tab.id
          ? 'bg-primary text-primary-foreground shadow-md'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
      )"
      @click="goToTab(tab.id, $event)"
    >
      <component
        :is="tab.icon"
        class="w-4 h-4"
      />
      <span class="hidden sm:inline">{{ tab.label }}</span>
    </button>
  </div>
</template>