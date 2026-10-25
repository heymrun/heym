import { computed, onBeforeUnmount, watch, type ComputedRef, type Ref } from "vue";
import { useThrottleFn } from "@vueuse/core";

import type { AssistantMirror, MirroredAssistantMessage } from "@/features/collab/types";
import {
  followedPerson,
  followedSignals,
  followedTranscript,
  followerCount,
  localFollowSignals,
} from "@/features/collab/followSignals";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

// Panel, mode and draft ride in presence and feel live; the transcript is sent on its own,
// only when it changes, so typing never resends the whole conversation.
const LIVE_MS = 120;
const TRANSCRIPT_MS = 250;
const MAX_MESSAGES = 20;
const MAX_CHARS = 4000;
const MAX_DRAFT_CHARS = 2000;

type AssistantMode = "agent" | "ask";

interface AssistantSource {
  open: Ref<boolean>;
  mode: Ref<AssistantMode>;
  draft: Ref<string>;
  messages: Ref<Array<{ id: string; role: "user" | "assistant"; content: string }>>;
}

export interface AssistantMirrorView {
  mirrored: ComputedRef<AssistantMirror | null>;
  transcript: ComputedRef<MirroredAssistantMessage[]>;
  /** Whose messages are shown while mirroring, for the user avatar. */
  author: ComputedRef<{ userId: string; name: string } | null>;
}

/** Shares this tab's AI Assistant with followers, and mirrors the followed person's. */
export function useAssistantMirror(source: AssistantSource): AssistantMirrorView {
  const collab = useCollabContext();

  function snapshot(): MirroredAssistantMessage[] {
    return source.messages.value
      .filter((message) => message.content.length > 0)
      .slice(-MAX_MESSAGES)
      .map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content.slice(0, MAX_CHARS),
      }));
  }

  const reportLive = useThrottleFn(
    () => {
      localFollowSignals.assistant = followerCount.value > 0
        ? {
            open: source.open.value,
            mode: source.mode.value,
            draft: source.draft.value.slice(0, MAX_DRAFT_CHARS),
          }
        : null;
    },
    LIVE_MS,
    true,
  );
  watch([source.open, source.mode, source.draft, followerCount], () => {
    void reportLive();
  }, { immediate: true });

  const sendTranscript = useThrottleFn(
    () => {
      if (followerCount.value > 0) collab?.sendAssistantTranscript(snapshot());
    },
    TRANSCRIPT_MS,
    true,
  );
  watch(source.messages, () => {
    void sendTranscript();
  }, { deep: true });
  watch(followerCount, (count, previous) => {
    if (count > (previous ?? 0)) void sendTranscript();
  });

  const mirrored = computed<AssistantMirror | null>(
    () => followedSignals.value?.assistant ?? null,
  );
  const transcript = computed<MirroredAssistantMessage[]>(() => followedTranscript.value);
  const author = computed(() => (mirrored.value ? followedPerson.value : null));

  // While mirroring, mode and draft show the followed person's; this tab's own come back after.
  let own: { mode: AssistantMode; draft: string } | null = null;
  watch(
    mirrored,
    (mirror) => {
      if (mirror) {
        if (!own) own = { mode: source.mode.value, draft: source.draft.value };
        if (source.open.value !== mirror.open) source.open.value = mirror.open;
        if (source.mode.value !== mirror.mode) source.mode.value = mirror.mode;
        if (source.draft.value !== mirror.draft) source.draft.value = mirror.draft;
      } else if (own) {
        source.mode.value = own.mode;
        source.draft.value = own.draft;
        own = null;
      }
    },
    { deep: true },
  );
  onBeforeUnmount(() => {
    localFollowSignals.assistant = null;
  });

  return { mirrored, transcript, author };
}
