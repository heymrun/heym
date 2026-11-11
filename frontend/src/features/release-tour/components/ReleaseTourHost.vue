<script setup lang="ts">
import { computed, ref, type ComponentPublicInstance } from "vue";
import { useElementBounding, useMediaQuery, useMutationObserver } from "@vueuse/core";

import ReleaseFeatureTour from "@/features/release-tour/components/ReleaseFeatureTour.vue";
import ReleaseTourLauncher from "@/features/release-tour/components/ReleaseTourLauncher.vue";
import { useReleaseTour } from "@/features/release-tour/useReleaseTour";

interface Props {
  /** Whether the host page allows the tour panel to open over its content. */
  eligible?: boolean;
  /** CSS selector for the header slot the launcher button renders into. */
  launcherTarget?: string;
}

const props = withDefaults(defineProps<Props>(), {
  eligible: true,
  launcherTarget: "#release-tour-launcher-slot",
});

// Desktop only: there is no room for this alongside the mobile toolbar and FAB.
const isMobile = useMediaQuery("(max-width: 767px)");

function readShowcaseIntroOpen(): boolean {
  if (typeof document === "undefined") return false;
  return document.body.dataset.heymShowcaseIntroOpen === "true";
}

const isShowcaseIntroOpen = ref(readShowcaseIntroOpen());

useMutationObserver(
  computed(() => (typeof document === "undefined" ? null : document.body)),
  () => {
    isShowcaseIntroOpen.value = readShowcaseIntroOpen();
  },
  { attributes: true, attributeFilter: ["data-heym-showcase-intro-open"] },
);

const featureAvailable = computed(() => props.eligible && !isMobile.value);
// The per-screen intro video owns the screen, so only the *auto* open waits it
// out. The header button stays available the whole time.
const autoOpenAllowed = computed(() => featureAvailable.value && !isShowcaseIntroOpen.value);

const { activeTour, isOpen, hasUnseenRelease, openTour, completeTour } =
  useReleaseTour(autoOpenAllowed);

// Blocking overlays hide the panel, while the header keeps its layout.
const showLauncher = computed(() => !isMobile.value && activeTour.value !== null);

// The panel hangs off the launcher button, which lives in the header via Teleport.
const launcherRef = ref<ComponentPublicInstance | null>(null);
const launcherEl = computed(() => (launcherRef.value?.$el as HTMLElement | null) ?? null);
const { left: launcherLeft, bottom: launcherBottom } = useElementBounding(launcherEl);
</script>

<template>
  <Teleport
    v-if="showLauncher && activeTour"
    defer
    :to="launcherTarget"
  >
    <ReleaseTourLauncher
      ref="launcherRef"
      :label="activeTour.label"
      :has-unseen-release="hasUnseenRelease"
      @open="openTour"
    />
  </Teleport>

  <ReleaseFeatureTour
    :release="activeTour"
    :open="isOpen && featureAvailable"
    :anchor-left="launcherLeft"
    :anchor-bottom="launcherBottom"
    @complete="completeTour"
  />
</template>
