import type { Component } from "vue";

import ChatWidgetRevertTourVisual from "@/features/release-tour/components/visuals/ChatWidgetRevertTourVisual.vue";
import DecisionRerankerTourVisual from "@/features/release-tour/components/visuals/DecisionRerankerTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import McpEndpointTourVisual from "@/features/release-tour/components/visuals/McpEndpointTourVisual.vue";
import RagMediaUploadTourVisual from "@/features/release-tour/components/visuals/RagMediaUploadTourVisual.vue";
import VoiceTranscribeTourVisual from "@/features/release-tour/components/visuals/VoiceTranscribeTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "voice-transcribe": VoiceTranscribeTourVisual,
  "decision-reranker": DecisionRerankerTourVisual,
  "rag-media-upload": RagMediaUploadTourVisual,
  "chat-widget-revert": ChatWidgetRevertTourVisual,
  "mcp-endpoint": McpEndpointTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
