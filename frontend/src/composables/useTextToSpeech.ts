import { computed, ref, type ComputedRef, type Ref } from "vue";

import { voiceApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

const audio = typeof Audio !== "undefined" ? new Audio() : null;
const playingId = ref<string | null>(null);
let currentUrl: string | null = null;

function releaseUrl(): void {
  if (currentUrl) {
    URL.revokeObjectURL(currentUrl);
    currentUrl = null;
  }
}

if (audio) {
  audio.addEventListener("ended", () => {
    playingId.value = null;
    releaseUrl();
  });
}

function stop(): void {
  if (audio) {
    audio.pause();
    audio.currentTime = 0;
  }
  releaseUrl();
  playingId.value = null;
}

interface UseTextToSpeech {
  playingId: Ref<string | null>;
  isConfigured: ComputedRef<boolean>;
  speak: (id: string, text: string) => Promise<void>;
  stop: () => void;
}

export function useTextToSpeech(): UseTextToSpeech {
  const authStore = useAuthStore();
  const isConfigured = computed(
    () => !!authStore.user?.tts_credential_id && !!authStore.user?.tts_voice_id,
  );

  async function speak(id: string, text: string): Promise<void> {
    if (!audio) return;
    if (playingId.value === id) {
      stop();
      return;
    }
    stop();
    const trimmed = text.trim();
    if (!trimmed) return;
    const blob = await voiceApi.tts(trimmed);
    currentUrl = URL.createObjectURL(blob);
    audio.src = currentUrl;
    playingId.value = id;
    await audio.play();
  }

  return { playingId, isConfigured, speak, stop };
}
