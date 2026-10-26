import type { Component } from "vue";

import AgentSuiteTourVisual from "@/features/release-tour/components/visuals/AgentSuiteTourVisual.vue";
import CanvasCollaborationTourVisual from "@/features/release-tour/components/visuals/CanvasCollaborationTourVisual.vue";
import ChatEvalsTourVisual from "@/features/release-tour/components/visuals/ChatEvalsTourVisual.vue";
import ConcurrencyLimitTourVisual from "@/features/release-tour/components/visuals/ConcurrencyLimitTourVisual.vue";
import NodeAiEditTourVisual from "@/features/release-tour/components/visuals/NodeAiEditTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "agent-suite": AgentSuiteTourVisual,
  "canvas-collaboration": CanvasCollaborationTourVisual,
  "chat-evals": ChatEvalsTourVisual,
  "concurrency-limit": ConcurrencyLimitTourVisual,
  "node-ai-edit": NodeAiEditTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
