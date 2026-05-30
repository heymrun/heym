<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { Mic, MicOff, X } from "lucide-vue-next";

import type { Message } from "@/types/chat";
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

function stripMarkdown(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return (div.textContent || "").trim();
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

watch(
  () => props.open,
  async (open) => {
    if (open) {
      lastUserText.value = "";
      lastAssistantText.value = "";
      spokenForMessageId = null;
      await voice.start();
    } else {
      voice.teardown();
      tts.stop();
    }
  },
);

function close(): void {
  voice.teardown();
  tts.stop();
  emit("close");
}

onBeforeUnmount(() => {
  voice.teardown();
  tts.stop();
});
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex flex-col items-center justify-between bg-background/95 backdrop-blur-md px-6 py-10 sm:py-16"
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
          'animate-pulse': voice.state.value === 'listening' || voice.state.value === 'speaking',
        }"
      >
        <div
          class="h-24 w-24 rounded-full bg-primary/30 transition-transform duration-300 sm:h-32 sm:w-32"
          :class="{
            'scale-110': voice.state.value === 'speaking',
            'scale-90': voice.state.value === 'idle',
          }"
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
</template>
