import type { Component } from "vue";

import CodexSignInTourVisual from "@/features/release-tour/components/visuals/CodexSignInTourVisual.vue";
import GoogleTriggersTourVisual from "@/features/release-tour/components/visuals/GoogleTriggersTourVisual.vue";
import HeymWorkTourVisual from "@/features/release-tour/components/visuals/HeymWorkTourVisual.vue";
import NodeAiEditTourVisual from "@/features/release-tour/components/visuals/NodeAiEditTourVisual.vue";
import SlackBotTourVisual from "@/features/release-tour/components/visuals/SlackBotTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "codex-device-sign-in": CodexSignInTourVisual,
  "google-triggers": GoogleTriggersTourVisual,
  "heym-work": HeymWorkTourVisual,
  "node-ai-edit": NodeAiEditTourVisual,
  "slack-bot": SlackBotTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
