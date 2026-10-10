import type { Component } from "vue";

import AssistantDataTablesTourVisual from "@/features/release-tour/components/visuals/AssistantDataTablesTourVisual.vue";
import AssistantYoloTourVisual from "@/features/release-tour/components/visuals/AssistantYoloTourVisual.vue";
import DashboardHitlTourVisual from "@/features/release-tour/components/visuals/DashboardHitlTourVisual.vue";
import EnableNodeTourVisual from "@/features/release-tour/components/visuals/EnableNodeTourVisual.vue";
import SkillZipTourVisual from "@/features/release-tour/components/visuals/SkillZipTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "assistant-data-tables": AssistantDataTablesTourVisual,
  "assistant-yolo-mode": AssistantYoloTourVisual,
  "dashboard-hitl": DashboardHitlTourVisual,
  "enable-node": EnableNodeTourVisual,
  "skill-zip": SkillZipTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
