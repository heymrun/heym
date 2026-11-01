import type { Component } from "vue";

import A2AAgentTourVisual from "@/features/release-tour/components/visuals/A2AAgentTourVisual.vue";
import AgentSuiteTourVisual from "@/features/release-tour/components/visuals/AgentSuiteTourVisual.vue";
import ChatEvalsTourVisual from "@/features/release-tour/components/visuals/ChatEvalsTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import FileAnalysisTourVisual from "@/features/release-tour/components/visuals/FileAnalysisTourVisual.vue";
import PlanningWidgetsTourVisual from "@/features/release-tour/components/visuals/PlanningWidgetsTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "file-analysis": FileAnalysisTourVisual,
  "planning-widgets": PlanningWidgetsTourVisual,
  "a2a-agent": A2AAgentTourVisual,
  "agent-suite": AgentSuiteTourVisual,
  "chat-evals": ChatEvalsTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
