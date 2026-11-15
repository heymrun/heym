import type { Component } from "vue";

import ChatWidgetRevertTourVisual from "@/features/release-tour/components/visuals/ChatWidgetRevertTourVisual.vue";
import DecisionRerankerTourVisual from "@/features/release-tour/components/visuals/DecisionRerankerTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import ImapAttachmentsTourVisual from "@/features/release-tour/components/visuals/ImapAttachmentsTourVisual.vue";
import McpEndpointTourVisual from "@/features/release-tour/components/visuals/McpEndpointTourVisual.vue";
import RagMediaUploadTourVisual from "@/features/release-tour/components/visuals/RagMediaUploadTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "decision-reranker": DecisionRerankerTourVisual,
  "rag-media-upload": RagMediaUploadTourVisual,
  "chat-widget-revert": ChatWidgetRevertTourVisual,
  "imap-attachments": ImapAttachmentsTourVisual,
  "mcp-endpoint": McpEndpointTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
