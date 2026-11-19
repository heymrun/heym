import type { Component } from "vue";

import FallbackTourVisual from "@/features/release-tour/components/visuals/FallbackTourVisual.vue";
import GmailTriggerTourVisual from "@/features/release-tour/components/visuals/GmailTriggerTourVisual.vue";
import MailSendTourVisual from "@/features/release-tour/components/visuals/MailSendTourVisual.vue";
import OutlookCalendarTourVisual from "@/features/release-tour/components/visuals/OutlookCalendarTourVisual.vue";
import OutlookTriggerTourVisual from "@/features/release-tour/components/visuals/OutlookTriggerTourVisual.vue";
import RunHistoryEncryptionTourVisual from "@/features/release-tour/components/visuals/RunHistoryEncryptionTourVisual.vue";

/** Maps a section's `tourVisual` key to the mock UI that demonstrates it. */
export const TOUR_VISUALS: Record<string, Component> = {
  "gmail-trigger": GmailTriggerTourVisual,
  "outlook-trigger": OutlookTriggerTourVisual,
  "outlook-calendar": OutlookCalendarTourVisual,
  "mail-send": MailSendTourVisual,
  "run-history-encryption": RunHistoryEncryptionTourVisual,
};

export function resolveTourVisual(key: string): Component {
  return TOUR_VISUALS[key] ?? FallbackTourVisual;
}
