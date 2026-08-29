import {
  computed,
  onUnmounted,
  ref,
  toValue,
  watch,
  type ComputedRef,
  type MaybeRefOrGetter,
} from "vue";

import { RELEASE_REGISTRY } from "@/features/release-tour/releaseRegistry";
import {
  buildReleaseTourCatalog,
  buildReleaseTours,
  selectPendingReleaseTour,
} from "@/features/release-tour/releaseTourMapper";
import { appendSeenReleaseId, readSeenReleaseIds } from "@/features/release-tour/releaseTourStorage";
import type { ReleaseTour } from "@/features/release-tour/releaseTour.types";

/** Lets the page settle before the popup slides in. */
const AUTO_OPEN_DELAY_MS = 900;

export interface UseReleaseTourResult {
  activeTour: ComputedRef<ReleaseTour | null>;
  isOpen: ComputedRef<boolean>;
  hasUnseenRelease: ComputedRef<boolean>;
  openTour: () => void;
  completeTour: () => void;
}

/**
 * Wires the release registry to persisted "seen" state. `eligible` is the
 * host page's own visibility rule; the tour never auto-opens without it.
 */
export function useReleaseTour(eligible: MaybeRefOrGetter<boolean>): UseReleaseTourResult {
  const tours = buildReleaseTours(RELEASE_REGISTRY);
  const catalogTour = buildReleaseTourCatalog(RELEASE_REGISTRY);
  const seenReleaseIds = ref<string[]>(readSeenReleaseIds());
  const isOpen = ref(false);
  const isBrowsingCatalog = ref(false);
  let autoOpenTimeoutId: number | null = null;

  const pendingTour = computed(() => selectPendingReleaseTour(tours, seenReleaseIds.value));
  const newestTour = computed<ReleaseTour | null>(() => pendingTour.value ?? tours[0] ?? null);
  /** The launcher always opens the complete product catalog, while prompts stay concise. */
  const activeTour = computed<ReleaseTour | null>(() =>
    isBrowsingCatalog.value ? catalogTour ?? newestTour.value : newestTour.value,
  );
  const hasUnseenRelease = computed(() => pendingTour.value !== null);

  function clearAutoOpenTimeout(): void {
    if (autoOpenTimeoutId === null) return;
    window.clearTimeout(autoOpenTimeoutId);
    autoOpenTimeoutId = null;
  }

  function openTour(): void {
    clearAutoOpenTimeout();
    if (!activeTour.value) return;
    isBrowsingCatalog.value = true;
    isOpen.value = true;
  }

  function completeTour(): void {
    clearAutoOpenTimeout();
    const tour = newestTour.value;
    if (tour) {
      seenReleaseIds.value = appendSeenReleaseId(tour.versionedReleaseId);
    }
    isBrowsingCatalog.value = false;
    isOpen.value = false;
  }

  watch(
    () => toValue(eligible) && pendingTour.value !== null,
    (shouldAutoOpen) => {
      clearAutoOpenTimeout();
      if (!shouldAutoOpen || isOpen.value) return;

      autoOpenTimeoutId = window.setTimeout(() => {
        autoOpenTimeoutId = null;
        isOpen.value = true;
      }, AUTO_OPEN_DELAY_MS);
    },
    { immediate: true },
  );

  onUnmounted(clearAutoOpenTimeout);

  return {
    activeTour,
    isOpen: computed(() => isOpen.value),
    hasUnseenRelease,
    openTour,
    completeTour,
  };
}
