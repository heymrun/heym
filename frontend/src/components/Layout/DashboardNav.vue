<script setup lang="ts">
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Activity,
  BarChart3,
  CalendarClock,
  Database,
  FlaskConical,
  HardDrive,
  Key,
  LayoutDashboard,
  LayoutTemplate,
  MessageCircle,
  Server,
  SquareKanban,
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
  { id: "board", label: "Board", icon: SquareKanban },
  { id: "schedules", label: "Scheduled", icon: CalendarClock },
  { id: "templates", label: "Templates", icon: LayoutTemplate },
  { id: "globalvariables", label: "Variables", icon: Variable },
  { id: "chat", label: "Chat", icon: MessageCircle },
  { id: "drive", label: "Drive", icon: HardDrive },
  { id: "datatable", label: "DataTable", icon: Table2 },
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "vectorstores", label: "Vectors", icon: Database },
  { id: "mcp", label: "MCP", icon: Server },
  { id: "traces", label: "Traces", icon: Activity },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "credentials", label: "Credentials", icon: Key },
  { id: "evals", label: "Evals", icon: FlaskConical },
  { id: "teams", label: "Teams", icon: Users },
  { id: "logs", label: "Logs", icon: Terminal },
] as const;

const activeTab = computed(() => {
  if (route.path === "/evals") return "evals";
  if (route.path.startsWith("/chats")) return "chat";
  const tabParam = route.query.tab as string;
  if (
    tabParam === "board" ||
    tabParam === "schedules" ||
    tabParam === "credentials" ||
    tabParam === "globalvariables" ||
    tabParam === "vectorstores" ||
    tabParam === "mcp" ||
    tabParam === "traces" ||
    tabParam === "analytics" ||
    tabParam === "dashboard" ||
    tabParam === "logs" ||
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
  if (tabId === "chat") return "/chats";
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
  if (tabId === "chat") {
    router.push("/chats");
    return;
  }
  if (tabId === "workflows") {
    router.push("/");
    return;
  }
  router.push({ path: "/", query: { tab: tabId } });
}

const tabContainerRef = ref<HTMLElement | null>(null);
const showLeftShadow = ref(false);
const showRightShadow = ref(false);

function updateShadows(): void {
  const container = tabContainerRef.value;
  if (!container) return;
  showLeftShadow.value = container.scrollLeft > 2;
  showRightShadow.value = container.scrollLeft + container.clientWidth < container.scrollWidth - 2;
}

let resizeObserver: ResizeObserver | null = null;

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

    updateShadows();

    resizeObserver = new ResizeObserver(() => updateShadows());
    resizeObserver.observe(container);

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

onUnmounted(() => {
  resizeObserver?.disconnect();
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
  <div class="relative mb-5 w-full shrink-0">
    <Transition name="tab-fade">
      <div
        v-if="showLeftShadow"
        class="pointer-events-none absolute left-0 top-0 bottom-0 w-10 z-10 rounded-l-2xl"
        style="background: linear-gradient(to right, hsl(var(--background)) 0%, transparent 100%)"
      />
    </Transition>
    <Transition name="tab-fade">
      <div
        v-if="showRightShadow"
        class="pointer-events-none absolute right-0 top-0 bottom-0 w-10 z-10 rounded-r-2xl"
        style="background: linear-gradient(to left, hsl(var(--background)) 0%, transparent 100%)"
      />
    </Transition>

    <div
      ref="tabContainerRef"
      :class="cn(
        'tab-container flex items-center gap-5 p-2 sm:p-2.5 rounded-2xl bg-card/60 border border-border/50 overflow-x-auto backdrop-blur-md shadow-sm scrollbar-thin w-full',
      )"
      @scroll="updateShadows"
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
          class="tab-icon w-4 h-4"
        />
        <span class="hidden sm:inline">{{ tab.label }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.tab-fade-enter-active,
.tab-fade-leave-active {
  transition: opacity 0.15s ease;
}
.tab-fade-enter-from,
.tab-fade-leave-to {
  opacity: 0;
}

/* --- icon hover animation keyframes --- */
@keyframes icon-spin {
  0%   { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

@keyframes icon-tick {
  0%, 100% { transform: rotate(0deg); }
  25%       { transform: rotate(-15deg); }
  75%       { transform: rotate(10deg); }
}

@keyframes icon-pop {
  0%, 100% { transform: scale(1); }
  50%       { transform: scale(1.25); }
}

@keyframes icon-bounce {
  0%, 100% { transform: translateY(0); }
  40%       { transform: translateY(-4px); }
  70%       { transform: translateY(-2px); }
}

@keyframes icon-pulse {
  0%, 100% { transform: scale(1); }
  40%       { transform: scale(1.2); }
  70%       { transform: scale(0.95); }
}

@keyframes icon-slide {
  0%, 100% { transform: translateX(0); }
  40%       { transform: translateX(3px); }
  70%       { transform: translateX(1px); }
}

@keyframes icon-rotate {
  0%, 100% { transform: rotate(0deg); }
  40%       { transform: rotate(20deg); }
  70%       { transform: rotate(10deg); }
}

@keyframes icon-blink {
  0%, 100% { opacity: 1; }
  40%       { opacity: 0.3; }
  70%       { opacity: 0.7; }
}

@keyframes icon-wiggle {
  0%, 100% { transform: rotate(0deg); }
  15%       { transform: rotate(-12deg); }
  35%       { transform: rotate(12deg); }
  55%       { transform: rotate(-6deg); }
  75%       { transform: rotate(6deg); }
}

@keyframes icon-grow {
  0%, 100% { transform: scaleY(1); }
  30%       { transform: scaleY(0.7); }
  60%       { transform: scaleY(1.1); }
}

@keyframes icon-shake {
  0%, 100% { transform: translateX(0); }
  20%       { transform: translateX(-3px); }
  40%       { transform: translateX(3px); }
  60%       { transform: translateX(-2px); }
  80%       { transform: translateX(2px); }
}

/* --- per-tab hover animations --- */
.tab-item[data-tab-id="workflows"]:hover       .tab-icon { animation: icon-spin   0.45s ease-out; }
.tab-item[data-tab-id="board"]:hover           .tab-icon { animation: icon-pop    0.35s ease-out; }
.tab-item[data-tab-id="schedules"]:hover       .tab-icon { animation: icon-tick   0.40s ease-out; }
.tab-item[data-tab-id="templates"]:hover       .tab-icon { animation: icon-pop    0.35s ease-out; }
.tab-item[data-tab-id="dashboard"]:hover       .tab-icon { animation: icon-pop    0.35s ease-out; }
.tab-item[data-tab-id="globalvariables"]:hover .tab-icon { animation: icon-bounce 0.40s ease-out; }
.tab-item[data-tab-id="chat"]:hover            .tab-icon { animation: icon-pulse  0.40s ease-out; }
.tab-item[data-tab-id="drive"]:hover           .tab-icon { animation: icon-spin   0.50s ease-out; }
.tab-item[data-tab-id="datatable"]:hover       .tab-icon { animation: icon-slide  0.35s ease-out; }
.tab-item[data-tab-id="credentials"]:hover     .tab-icon { animation: icon-rotate 0.40s ease-out; }
.tab-item[data-tab-id="vectorstores"]:hover    .tab-icon { animation: icon-pulse  0.40s ease-out; }
.tab-item[data-tab-id="mcp"]:hover             .tab-icon { animation: icon-blink  0.50s ease-out; }
.tab-item[data-tab-id="traces"]:hover          .tab-icon { animation: icon-wiggle 0.50s ease-out; }
.tab-item[data-tab-id="analytics"]:hover       .tab-icon { animation: icon-grow   0.40s ease-out; }
.tab-item[data-tab-id="evals"]:hover           .tab-icon { animation: icon-shake  0.45s ease-out; }
.tab-item[data-tab-id="teams"]:hover           .tab-icon { animation: icon-bounce 0.40s ease-out; }
.tab-item[data-tab-id="logs"]:hover            .tab-icon { animation: icon-blink  0.50s ease-out; }

@media (prefers-reduced-motion: reduce) {
  .tab-icon {
    animation: none !important;
  }
}
</style>