import type { Component } from "vue";

import AssistantDataTablesTourVisual from "@/features/release-tour/components/visuals/AssistantDataTablesTourVisual.vue";
import AssistantYoloTourVisual from "@/features/release-tour/components/visuals/AssistantYoloTourVisual.vue";
import ChatCredentialsTourVisual from "@/features/release-tour/components/visuals/ChatCredentialsTourVisual.vue";
import DashboardSharingTourVisual from "@/features/release-tour/components/visuals/DashboardSharingTourVisual.vue";
import EvalsJudgeTourVisual from "@/features/release-tour/components/visuals/EvalsJudgeTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "assistant-data-tables": AssistantDataTablesTourVisual,
  "assistant-yolo-mode": AssistantYoloTourVisual,
  "chat-credentials": ChatCredentialsTourVisual,
  "dashboard-sharing": DashboardSharingTourVisual,
  "evals-judge": EvalsJudgeTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
