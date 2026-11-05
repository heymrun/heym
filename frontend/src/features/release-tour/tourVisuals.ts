import type { Component } from "vue";

import A2AAgentTourVisual from "@/features/release-tour/components/visuals/A2AAgentTourVisual.vue";
import AgentSuiteTourVisual from "@/features/release-tour/components/visuals/AgentSuiteTourVisual.vue";
import BoardTaskFieldsTourVisual from "@/features/release-tour/components/visuals/BoardTaskFieldsTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import FileAnalysisTourVisual from "@/features/release-tour/components/visuals/FileAnalysisTourVisual.vue";
import PlanningWidgetsTourVisual from "@/features/release-tour/components/visuals/PlanningWidgetsTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "board-task-fields": BoardTaskFieldsTourVisual,
  "file-analysis": FileAnalysisTourVisual,
  "planning-widgets": PlanningWidgetsTourVisual,
  "a2a-agent": A2AAgentTourVisual,
  "agent-suite": AgentSuiteTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
