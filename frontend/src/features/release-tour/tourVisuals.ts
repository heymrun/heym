import type { Component } from "vue";

import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import GmailTriggerTourVisual from "@/features/release-tour/components/visuals/GmailTriggerTourVisual.vue";
import ImapAttachmentsTourVisual from "@/features/release-tour/components/visuals/ImapAttachmentsTourVisual.vue";
import McpEndpointTourVisual from "@/features/release-tour/components/visuals/McpEndpointTourVisual.vue";
import OutlookCalendarTourVisual from "@/features/release-tour/components/visuals/OutlookCalendarTourVisual.vue";
import OutlookTriggerTourVisual from "@/features/release-tour/components/visuals/OutlookTriggerTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "imap-attachments": ImapAttachmentsTourVisual,
  "mcp-endpoint": McpEndpointTourVisual,
  "gmail-trigger": GmailTriggerTourVisual,
  "outlook-trigger": OutlookTriggerTourVisual,
  "outlook-calendar": OutlookCalendarTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
