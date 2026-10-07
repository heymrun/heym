import { createInteractiveVoice, type InteractiveVoice } from "@/composables/interactiveVoice";
import { voiceApi } from "@/services/api";

/** Heym's hands-free voice session: the microphone loop over Heym's speech-to-text API. */
export function useInteractiveVoice(onUtterance: (text: string) => void): InteractiveVoice {
  return createInteractiveVoice((audio) => voiceApi.stt(audio), onUtterance);
}
