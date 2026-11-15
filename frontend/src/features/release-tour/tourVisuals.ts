import type { Component } from "vue";

import ChatWidgetRevertTourVisual from "@/features/release-tour/components/visuals/ChatWidgetRevertTourVisual.vue";
import DecisionRerankerTourVisual from "@/features/release-tour/components/visuals/DecisionRerankerTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import GoogleMeetBusyDetailsTourVisual from "@/features/release-tour/components/visuals/GoogleMeetBusyDetailsTourVisual.vue";
import ImapAttachmentsTourVisual from "@/features/release-tour/components/visuals/ImapAttachmentsTourVisual.vue";
import RagMediaUploadTourVisual from "@/features/release-tour/components/visuals/RagMediaUploadTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "google-meet-busy-details": GoogleMeetBusyDetailsTourVisual,
  "decision-reranker": DecisionRerankerTourVisual,
  "rag-media-upload": RagMediaUploadTourVisual,
  "chat-widget-revert": ChatWidgetRevertTourVisual,
  "imap-attachments": ImapAttachmentsTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
