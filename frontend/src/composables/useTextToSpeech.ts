import { computed, type ComputedRef } from "vue";

import { createTextToSpeechPlayer, type TextToSpeechPlayer } from "@/composables/textToSpeechPlayer";
import { voiceApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

interface UseTextToSpeech extends TextToSpeechPlayer {
  isConfigured: ComputedRef<boolean>;
}

/** Heym's text to speech: the shared player over Heym's voice API and the user's voice settings. */
export function useTextToSpeech(): UseTextToSpeech {
  const authStore = useAuthStore();
  const isConfigured = computed(
    () => !!authStore.user?.tts_credential_id && !!authStore.user?.tts_voice_id,
  );
  const player = createTextToSpeechPlayer({
    streamUrl: (text) => voiceApi.streamUrl(text),
    synthesize: (text) => voiceApi.tts(text),
  });
  return { ...player, isConfigured };
}
