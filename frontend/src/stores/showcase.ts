import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type { ShowcaseContext } from "@/features/showcase/showcase.types";

interface ShowcasePersistedState {
  activeContext: ShowcaseContext | null;
  isDesktopPanelOpen: boolean;
  isMobileSheetOpen: boolean;
  seenTeasers: Partial<Record<ShowcaseContext, boolean>>;
  lastExpandedDetailIdByContext: Partial<Record<ShowcaseContext, string | null>>;
}

const SHOWCASE_STORAGE_KEY = "heym-contextual-showcase";

function createDefaultState(): ShowcasePersistedState {
  return {
    activeContext: null,
    isDesktopPanelOpen: false,
    isMobileSheetOpen: false,
    seenTeasers: {},
    lastExpandedDetailIdByContext: {},
  };
}

export const useShowcaseStore = defineStore("showcase", () => {
  const hydrated = ref(false);
  const activeContext = ref<ShowcaseContext | null>(null);
  const isDesktopPanelOpen = ref(false);
  const isMobileSheetOpen = ref(false);
  const visibleTeaserContext = ref<ShowcaseContext | null>(null);
  const seenTeasers = ref<Partial<Record<ShowcaseContext, boolean>>>({});
  const lastExpandedDetailIdByContext = ref<Partial<Record<ShowcaseContext, string | null>>>({});

  function hydrateState(): void {
    if (hydrated.value || typeof window === "undefined") return;

    try {
      const raw = window.localStorage.getItem(SHOWCASE_STORAGE_KEY);
      if (!raw) {
        hydrated.value = true;
        return;
      }

      const parsed = JSON.parse(raw) as Partial<ShowcasePersistedState>;
      activeContext.value = parsed.activeContext ?? null;
      isDesktopPanelOpen.value = parsed.isDesktopPanelOpen ?? false;
      isMobileSheetOpen.value = parsed.isMobileSheetOpen ?? false;
      seenTeasers.value = parsed.seenTeasers ?? {};
      lastExpandedDetailIdByContext.value = parsed.lastExpandedDetailIdByContext ?? {};
    } catch {
      const fallback = createDefaultState();
      activeContext.value = fallback.activeContext;
      isDesktopPanelOpen.value = fallback.isDesktopPanelOpen;
      isMobileSheetOpen.value = fallback.isMobileSheetOpen;
      seenTeasers.value = fallback.seenTeasers;
      lastExpandedDetailIdByContext.value = fallback.lastExpandedDetailIdByContext;
    } finally {
      hydrated.value = true;
    }
  }

  function saveState(): void {
    if (typeof window === "undefined") return;

    const nextState: ShowcasePersistedState = {
      activeContext: activeContext.value,
      isDesktopPanelOpen: isDesktopPanelOpen.value,
      isMobileSheetOpen: isMobileSheetOpen.value,
      seenTeasers: seenTeasers.value,
      lastExpandedDetailIdByContext: lastExpandedDetailIdByContext.value,
    };

    try {
      window.localStorage.setItem(SHOWCASE_STORAGE_KEY, JSON.stringify(nextState));
    } catch {
      // Ignore storage failures so the showcase still works without persistence.
    }
  }

  function setCurrentContext(context: ShowcaseContext | null): void {
    hydrateState();
    activeContext.value = context;
    saveState();
  }

  function hasSeenTeaser(context: ShowcaseContext): boolean {
    hydrateState();
    return seenTeasers.value[context] === true;
  }

  function showTeaser(context: ShowcaseContext): void {
    hydrateState();
    if (hasSeenTeaser(context)) return;
    visibleTeaserContext.value = context;
  }

  function hideTeaser(context?: ShowcaseContext | null): void {
    if (!context || visibleTeaserContext.value === context) {
      visibleTeaserContext.value = null;
    }
  }

  function markTeaserSeen(context: ShowcaseContext): void {
    hydrateState();
    seenTeasers.value = {
      ...seenTeasers.value,
      [context]: true,
    };
    hideTeaser(context);
    saveState();
  }

  function openDesktopPanel(): void {
    hydrateState();
    if (activeContext.value) {
      markTeaserSeen(activeContext.value);
    }
    isDesktopPanelOpen.value = true;
    isMobileSheetOpen.value = false;
    saveState();
  }

  function openMobileSheet(): void {
    hydrateState();
    if (activeContext.value) {
      markTeaserSeen(activeContext.value);
    }
    isDesktopPanelOpen.value = false;
    isMobileSheetOpen.value = true;
    saveState();
  }

  function closeAll(): void {
    hydrateState();
    isDesktopPanelOpen.value = false;
    isMobileSheetOpen.value = false;
    saveState();
  }

  function setExpandedDetail(context: ShowcaseContext, detailId: string | null): void {
    hydrateState();
    lastExpandedDetailIdByContext.value = {
      ...lastExpandedDetailIdByContext.value,
      [context]: detailId,
    };
    saveState();
  }

  const currentExpandedDetailId = computed<string | null>(() => {
    if (!activeContext.value) return null;
    return lastExpandedDetailIdByContext.value[activeContext.value] ?? null;
  });

  hydrateState();

  return {
    activeContext,
    currentExpandedDetailId,
    isDesktopPanelOpen,
    isMobileSheetOpen,
    lastExpandedDetailIdByContext,
    visibleTeaserContext,
    closeAll,
    hasSeenTeaser,
    hideTeaser,
    markTeaserSeen,
    openDesktopPanel,
    openMobileSheet,
    setCurrentContext,
    setExpandedDetail,
    showTeaser,
  };
});
