import { computed, ref, type ComputedRef, type Ref } from "vue";

import { voiceApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

// Beyond this URL length we POST and download the full clip instead of
// streaming via a GET query string, to stay well under proxy URL limits.
const MAX_STREAM_URL_LENGTH = 6000;

const audio = typeof Audio !== "undefined" ? new Audio() : null;
const playingId = ref<string | null>(null);
let currentUrl: string | null = null;

function releaseUrl(): void {
  if (currentUrl) {
    URL.revokeObjectURL(currentUrl);
    currentUrl = null;
  }
}

function reset(): void {
  playingId.value = null;
  releaseUrl();
}

function stop(): void {
  if (audio) {
    audio.pause();
    audio.currentTime = 0;
    audio.onended = null;
    audio.onerror = null;
  }
  reset();
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

  async function playDownloaded(id: string, text: string): Promise<void> {
    if (!audio) return;
    audio.onerror = (): void => {
      if (playingId.value === id) reset();
    };
    const blob = await voiceApi.tts(text);
    if (playingId.value !== id) return;
    currentUrl = URL.createObjectURL(blob);
    audio.src = currentUrl;
    await audio.play();
  }

  async function speak(id: string, text: string): Promise<void> {
    if (!audio) return;
    if (playingId.value === id) {
      stop();
      return;
    }
    stop();
    const trimmed = text.trim();
    if (!trimmed) return;
    playingId.value = id;
    audio.onended = (): void => {
      if (playingId.value === id) reset();
    };

    // Prefer progressive streaming so playback starts before the full clip is
    // generated. Fall back to a full download for very long text or if the
    // stream fails to start.
    const streamUrl = voiceApi.streamUrl(trimmed);
    if (streamUrl.length <= MAX_STREAM_URL_LENGTH) {
      // Ignore errors while the stream is starting so a failed start falls
      // through to the download path instead of clearing playback state.
      audio.onerror = null;
      try {
        audio.src = streamUrl;
        await audio.play();
        // Playback started; from now on, surface mid-stream failures.
        audio.onerror = (): void => {
          if (playingId.value === id) reset();
        };
        return;
      } catch {
        if (playingId.value !== id) return;
      }
    }

    await playDownloaded(id, trimmed);
  }

  return { playingId, isConfigured, speak, stop };
}
