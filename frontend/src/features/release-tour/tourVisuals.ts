import type { Component } from "vue";

import AccountSecurityTourVisual from "@/features/release-tour/components/visuals/AccountSecurityTourVisual.vue";
import BoardTaskFieldsTourVisual from "@/features/release-tour/components/visuals/BoardTaskFieldsTourVisual.vue";
import GoogleMeetTourVisual from "@/features/release-tour/components/visuals/GoogleMeetTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import FileAnalysisTourVisual from "@/features/release-tour/components/visuals/FileAnalysisTourVisual.vue";
import PlanningWidgetsTourVisual from "@/features/release-tour/components/visuals/PlanningWidgetsTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "board-task-fields": BoardTaskFieldsTourVisual,
  "file-analysis": FileAnalysisTourVisual,
  "planning-widgets": PlanningWidgetsTourVisual,
  "account-security": AccountSecurityTourVisual,
  "google-meet": GoogleMeetTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
