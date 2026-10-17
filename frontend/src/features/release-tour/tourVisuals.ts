import type { Component } from "vue";

import DashboardHitlTourVisual from "@/features/release-tour/components/visuals/DashboardHitlTourVisual.vue";
import EnableNodeTourVisual from "@/features/release-tour/components/visuals/EnableNodeTourVisual.vue";
import HeymWorkTourVisual from "@/features/release-tour/components/visuals/HeymWorkTourVisual.vue";
import JiraPatTourVisual from "@/features/release-tour/components/visuals/JiraPatTourVisual.vue";
import SkillZipTourVisual from "@/features/release-tour/components/visuals/SkillZipTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "dashboard-hitl": DashboardHitlTourVisual,
  "enable-node": EnableNodeTourVisual,
  "heym-work": HeymWorkTourVisual,
  "jira-pat-auth": JiraPatTourVisual,
  "skill-zip": SkillZipTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
