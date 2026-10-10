import { beforeEach, describe, expect, it, vi } from "vitest";

// The player's audio element is created when the module loads, so Audio must be stubbed first.
const { FakeAudio } = vi.hoisted(() => {
  class FakeAudioImpl {
    src = "";
    currentTime = 0;
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    play = vi.fn(async () => {});
    pause = vi.fn();
  }
  return { FakeAudio: FakeAudioImpl };
});
vi.hoisted(() => {
  vi.stubGlobal("Audio", FakeAudio);
});

import { createTextToSpeechPlayer, type SpeechSource } from "@/composables/textToSpeechPlayer";

function source(name: string): SpeechSource {
  return {
    streamUrl: vi.fn((text: string) => `https://${name}.test/tts?text=${text}`),
    synthesize: vi.fn(async () => new Blob(["audio"])),
  };
}

describe("createTextToSpeechPlayer", () => {
  beforeEach(() => createTextToSpeechPlayer(source("reset")).stop());

  it("streams from the source it was given", async () => {
    const work = source("work");
    const player = createTextToSpeechPlayer(work);

    await player.speak("m-1", " Hello ");

    expect(work.streamUrl).toHaveBeenCalledWith("Hello");
    expect(player.playingId.value).toBe("m-1");
  });

  it("shares one playback across players, so starting one clip stops the other", async () => {
    const readAloud = createTextToSpeechPlayer(source("chat"));
    const voiceMode = createTextToSpeechPlayer(source("voice"));

    await readAloud.speak("m-1", "First");
    await voiceMode.speak("iv-2", "Second");

    expect(readAloud.playingId.value).toBe("iv-2");
    voiceMode.stop();
    expect(readAloud.playingId.value).toBeNull();
  });
});
