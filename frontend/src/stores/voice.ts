import { defineStore } from "pinia";
import { ref } from "vue";

export const useVoiceStore = defineStore("voice", () => {
  // Incremented to ask the app shell to open User Settings on the Voice tab.
  const openVoiceSettingsSignal = ref(0);

  function requestVoiceSettings(): void {
    openVoiceSettingsSignal.value += 1;
  }

  return { openVoiceSettingsSignal, requestVoiceSettings };
});
