import type { Component } from "vue";

import ChatCredentialsTourVisual from "@/features/release-tour/components/visuals/ChatCredentialsTourVisual.vue";
import DecisionNodeTourVisual from "@/features/release-tour/components/visuals/DecisionNodeTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import ModelRouterTourVisual from "@/features/release-tour/components/visuals/ModelRouterTourVisual.vue";
import RagUpsertDeleteTourVisual from "@/features/release-tour/components/visuals/RagUpsertDeleteTourVisual.vue";
import ResponsesApiTourVisual from "@/features/release-tour/components/visuals/ResponsesApiTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "chat-credentials": ChatCredentialsTourVisual,
  "decision-node": DecisionNodeTourVisual,
  "model-router": ModelRouterTourVisual,
  "rag-upsert-delete": RagUpsertDeleteTourVisual,
  "responses-api": ResponsesApiTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
