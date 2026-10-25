import type { Component } from "vue";

import CanvasCollaborationTourVisual from "@/features/release-tour/components/visuals/CanvasCollaborationTourVisual.vue";
import CodexSignInTourVisual from "@/features/release-tour/components/visuals/CodexSignInTourVisual.vue";
import ConcurrencyLimitTourVisual from "@/features/release-tour/components/visuals/ConcurrencyLimitTourVisual.vue";
import NodeAiEditTourVisual from "@/features/release-tour/components/visuals/NodeAiEditTourVisual.vue";
import SlackBotTourVisual from "@/features/release-tour/components/visuals/SlackBotTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "canvas-collaboration": CanvasCollaborationTourVisual,
  "codex-device-sign-in": CodexSignInTourVisual,
  "concurrency-limit": ConcurrencyLimitTourVisual,
  "node-ai-edit": NodeAiEditTourVisual,
  "slack-bot": SlackBotTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
