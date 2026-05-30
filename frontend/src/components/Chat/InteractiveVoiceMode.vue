<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Mic, MicOff, X } from "lucide-vue-next";

import type { Message } from "@/types/chat";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { useInteractiveVoice, type VoiceState } from "@/composables/useInteractiveVoice";
import { useTextToSpeech } from "@/composables/useTextToSpeech";

const props = defineProps<{
  open: boolean;
  messages: Message[];
  isStreaming: boolean;
  onSend: (text: string) => Promise<void> | void;
}>();

const emit = defineEmits<{ close: [] }>();

const tts = useTextToSpeech();
const lastUserText = ref("");
const lastAssistantText = ref("");
let spokenForMessageId: string | null = null;

const voice = useInteractiveVoice((text: string) => {
  lastUserText.value = text;
  voice.setState("thinking");
  void props.onSend(text);
});

const stateLabel: Record<VoiceState, string> = {
  idle: "Paused",
  listening: "Listening…",
  transcribing: "Transcribing…",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

// Orb reacts to the live mic level while listening, otherwise rests/pulses.
const orbScale = computed(() => {
  if (voice.state.value === "listening") return 1 + voice.level.value * 0.7;
  if (voice.state.value === "speaking") return 1.1;
  if (voice.state.value === "idle") return 0.9;
  return 1;
});

// Strip markdown so the spoken text does not include symbols like * _ # ` or
// link syntax, which makes playback cleaner.
function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_~#>]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function waitForPlaybackEnd(): Promise<void> {
  return new Promise((resolve) => {
    const id = window.setInterval(() => {
      if (tts.playingId.value === null) {
        window.clearInterval(id);
        resolve();
      }
    }, 150);
  });
}

// When the assistant finishes streaming a new reply, speak it then resume listening.
watch(
  () => props.isStreaming,
  async (streaming, wasStreaming) => {
    if (wasStreaming && !streaming && props.open) {
      const last = props.messages[props.messages.length - 1];
      if (last && last.role === "assistant" && last.id !== spokenForMessageId) {
        spokenForMessageId = last.id;
        lastAssistantText.value = last.content;
        voice.setState("speaking");
        try {
          await tts.speak(`iv-${last.id}`, stripMarkdown(last.content));
        } catch {
          /* ignore synthesis errors */
        }
        await waitForPlaybackEnd();
        if (props.open && !voice.muted.value) await voice.start();
      }
    }
  },
);

// The global overlay back handler (useOverlayBackHandler) owns Escape and the
// mobile back button; it dispatches a dismiss event we subscribe to here.
let unsubscribeDismiss: (() => void) | null = null;

watch(
  () => props.open,
  async (open) => {
    if (open) {
      lastUserText.value = "";
      lastAssistantText.value = "";
      spokenForMessageId = null;
      unsubscribeDismiss = onDismissOverlays(() => close());
      await voice.start();
    } else {
      unsubscribeDismiss?.();
      unsubscribeDismiss = null;
      voice.teardown();
      tts.stop();
    }
  },
);

function close(): void {
  emit("close");
}

onBeforeUnmount(() => {
  unsubscribeDismiss?.();
  voice.teardown();
  tts.stop();
});
</script>

<template>
  <!-- Teleport to body so the overlay escapes WorkspaceShell's transformed
       (stacking-context) content wrapper; otherwise the Quick Workflows drawer
       and showcase buttons paint on top of it. -->
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[60] flex flex-col items-center justify-between bg-background px-6 py-10 sm:py-16"
    >
      <button
        type="button"
        class="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
        aria-label="Close voice mode"
        @click="close"
      >
        <X class="h-5 w-5" />
      </button>

      <div class="flex flex-1 flex-col items-center justify-center gap-8">
        <div
          class="relative flex h-40 w-40 items-center justify-center rounded-full bg-primary/10 sm:h-52 sm:w-52"
          :class="{
            'animate-pulse': voice.state.value === 'speaking',
          }"
        >
          <div
            class="h-24 w-24 rounded-full bg-primary/30 transition-transform duration-100 ease-out sm:h-32 sm:w-32"
            :style="{ transform: `scale(${orbScale})` }"
          />
        </div>
        <p class="text-sm font-medium text-muted-foreground">
          {{ stateLabel[voice.state.value] }}
        </p>
        <p
          v-if="lastUserText"
          class="max-w-md text-center text-sm text-foreground/80"
        >
          “{{ lastUserText }}”
        </p>
        <p
          v-if="voice.error.value"
          class="text-xs text-destructive"
        >
          {{ voice.error.value }}
        </p>
      </div>

      <div class="flex items-center gap-6">
        <button
          type="button"
          class="flex h-16 w-16 items-center justify-center rounded-full border border-border transition-colors"
          :class="voice.muted.value ? 'bg-muted text-muted-foreground' : 'bg-primary text-primary-foreground'"
          :aria-label="voice.muted.value ? 'Unmute microphone' : 'Mute microphone'"
          @click="voice.toggleMute()"
        >
          <MicOff
            v-if="voice.muted.value"
            class="h-6 w-6"
          />
          <Mic
            v-else
            class="h-6 w-6"
          />
        </button>
      </div>
    </div>
  </Teleport>
</template>
