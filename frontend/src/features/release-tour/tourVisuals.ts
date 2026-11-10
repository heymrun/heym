import type { Component } from "vue";

import AccountSecurityTourVisual from "@/features/release-tour/components/visuals/AccountSecurityTourVisual.vue";
import DecisionRerankerTourVisual from "@/features/release-tour/components/visuals/DecisionRerankerTourVisual.vue";
import GoogleMeetTourVisual from "@/features/release-tour/components/visuals/GoogleMeetTourVisual.vue";
import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import RagMediaUploadTourVisual from "@/features/release-tour/components/visuals/RagMediaUploadTourVisual.vue";
import VoiceTranscribeTourVisual from "@/features/release-tour/components/visuals/VoiceTranscribeTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "account-security": AccountSecurityTourVisual,
  "google-meet": GoogleMeetTourVisual,
  "voice-transcribe": VoiceTranscribeTourVisual,
  "decision-reranker": DecisionRerankerTourVisual,
  "rag-media-upload": RagMediaUploadTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
