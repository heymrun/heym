import type { Component } from "vue";

import CodeNodeTourVisual from "@/features/release-tour/components/visuals/CodeNodeTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import FolderIconsTourVisual from "@/features/release-tour/components/visuals/FolderIconsTourVisual.vue";
import HtmlOutputMapperTourVisual from "@/features/release-tour/components/visuals/HtmlOutputMapperTourVisual.vue";
import PlaywrightAiStepsTourVisual from "@/features/release-tour/components/visuals/PlaywrightAiStepsTourVisual.vue";
import SsoLoginTourVisual from "@/features/release-tour/components/visuals/SsoLoginTourVisual.vue";
import WorkflowListingTourVisual from "@/features/release-tour/components/visuals/WorkflowListingTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "code-node": CodeNodeTourVisual,
  "folder-icons": FolderIconsTourVisual,
  "html-output-mapper": HtmlOutputMapperTourVisual,
  "playwright-ai-steps": PlaywrightAiStepsTourVisual,
  "sso-login": SsoLoginTourVisual,
  "workflow-listing": WorkflowListingTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
