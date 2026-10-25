import { reactive, ref } from "vue";

import type { AssistantMirror, MirroredAssistantMessage } from "@/features/collab/types";

/** Editor UI state that lives inside components rather than the workflow store. */
export interface FollowSignals {
  leftPanelOpen: boolean;
  panelOpen: boolean;
  expression: { nodeId: string; field: string } | null;
  debugOpen: boolean;
  historyOpen: boolean;
  historyExecutionId: string | null;
  dialogs: string[];
  assistant: AssistantMirror | null;
}

export function emptyFollowSignals(): FollowSignals {
  return {
    leftPanelOpen: false,
    panelOpen: false,
    expression: null,
    debugOpen: false,
    historyOpen: false,
    historyExecutionId: null,
    dialogs: [],
    assistant: null,
  };
}

/** What this tab's components report about themselves; published to followers. */
export const localFollowSignals = reactive<FollowSignals>(emptyFollowSignals());

/** The leader's signals while this tab follows someone, null otherwise. Components mirror them. */
export const followedSignals = ref<FollowSignals | null>(null);

/** How many people follow this tab; the assistant transcript is only sent when someone does. */
export const followerCount = ref(0);

/** Who this tab follows, for showing their avatar on what they wrote. */
export const followedPerson = ref<{ userId: string; name: string } | null>(null);

/** The followed person's AI Assistant transcript, as they last sent it. */
export const followedTranscript = ref<MirroredAssistantMessage[]>([]);
