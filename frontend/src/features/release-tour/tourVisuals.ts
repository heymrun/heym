import type { Component } from "vue";

import A2AAgentTourVisual from "@/features/release-tour/components/visuals/A2AAgentTourVisual.vue";
import AgentSuiteTourVisual from "@/features/release-tour/components/visuals/AgentSuiteTourVisual.vue";
import CanvasCollaborationTourVisual from "@/features/release-tour/components/visuals/CanvasCollaborationTourVisual.vue";
import ChatEvalsTourVisual from "@/features/release-tour/components/visuals/ChatEvalsTourVisual.vue";
import ConcurrencyLimitTourVisual from "@/features/release-tour/components/visuals/ConcurrencyLimitTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "a2a-agent": A2AAgentTourVisual,
  "agent-suite": AgentSuiteTourVisual,
  "canvas-collaboration": CanvasCollaborationTourVisual,
  "chat-evals": ChatEvalsTourVisual,
  "concurrency-limit": ConcurrencyLimitTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
