import type { Component } from "vue";

import ChatCredentialsTourVisual from "@/features/release-tour/components/visuals/ChatCredentialsTourVisual.vue";
import DecisionNodeTourVisual from "@/features/release-tour/components/visuals/DecisionNodeTourVisual.vue";
import EvalsJudgeTourVisual from "@/features/release-tour/components/visuals/EvalsJudgeTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import ModelRouterTourVisual from "@/features/release-tour/components/visuals/ModelRouterTourVisual.vue";
import ResponsesApiTourVisual from "@/features/release-tour/components/visuals/ResponsesApiTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "chat-credentials": ChatCredentialsTourVisual,
  "decision-node": DecisionNodeTourVisual,
  "evals-judge": EvalsJudgeTourVisual,
  "model-router": ModelRouterTourVisual,
  "responses-api": ResponsesApiTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
