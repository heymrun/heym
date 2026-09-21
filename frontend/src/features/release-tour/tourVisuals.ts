import type { Component } from "vue";

import ClusterInstancesTourVisual from "@/features/release-tour/components/visuals/ClusterInstancesTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import PlaywrightAiStepsTourVisual from "@/features/release-tour/components/visuals/PlaywrightAiStepsTourVisual.vue";
import RagUpsertDeleteTourVisual from "@/features/release-tour/components/visuals/RagUpsertDeleteTourVisual.vue";
import ResponsesApiTourVisual from "@/features/release-tour/components/visuals/ResponsesApiTourVisual.vue";
import SsoLoginTourVisual from "@/features/release-tour/components/visuals/SsoLoginTourVisual.vue";
import SpanDetailsInspectorTourVisual from "@/features/release-tour/components/visuals/SpanDetailsInspectorTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "cluster-instances": ClusterInstancesTourVisual,
  "playwright-ai-steps": PlaywrightAiStepsTourVisual,
  "rag-upsert-delete": RagUpsertDeleteTourVisual,
  "responses-api": ResponsesApiTourVisual,
  "sso-login": SsoLoginTourVisual,
  "span-details-inspector": SpanDetailsInspectorTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
