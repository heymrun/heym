import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useInteractiveVoice } from "./useInteractiveVoice";
import { voiceApi } from "@/services/api";

// This composable touches a lot of browser surface: navigator.mediaDevices,
// MediaRecorder, AudioContext/AnalyserNode, and window.requestAnimationFrame.
// None of these exist in this project's Node test environment. Each is faked
// to the minimum shape the source actually reads/calls - see
// 06-faking-dependencies-and-stateful-code's "find the exact surface" rule.

class FakeMediaStreamTrack {
  stop = vi.fn();
}

class FakeMediaStream {
  private tracks = [new FakeMediaStreamTrack()];
  getTracks(): FakeMediaStreamTrack[] {
    return this.tracks;
  }
}

class FakeAnalyserNode {
  fftSize = 0;
  private amplitude = 0;
  /** Test control: every getFloatTimeDomainData call fills the buffer with this constant,
   *  so the RMS of a filled buffer is exactly this value - no need to replicate real audio data. */
  setAmplitude(value: number): void {
    this.amplitude = value;
  }
  getFloatTimeDomainData(buffer: Float32Array): void {
    buffer.fill(this.amplitude);
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  analyser: FakeAnalyserNode | null = null;

  constructor() {
    FakeAudioContext.instances.push(this);
  }

  createAnalyser(): FakeAnalyserNode {
    this.analyser = new FakeAnalyserNode();
    return this.analyser;
  }
  createMediaStreamSource(_stream: FakeMediaStream): { connect: (dest: unknown) => void } {
    return { connect: () => {} };
  }
  close(): Promise<void> {
    return Promise.resolve();
  }
}

class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  state: "inactive" | "recording" | "paused" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(public stream: FakeMediaStream) {
    FakeMediaRecorder.instances.push(this);
  }

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    this.state = "inactive";
    this.onstop?.();
  }

  emitChunk(content = "audio-bytes"): void {
    this.ondataavailable?.({ data: new Blob([content]) });
  }
}

// Node has real requestAnimationFrame via no browser equivalent - fake one
// that queues a callback instead of auto-firing it, so tests can drive the
// monitor() loop frame-by-frame deterministically rather than racing real
// 60fps timing.
class FakeRaf {
  private nextId = 1;
  private pending = new Map<number, FrameRequestCallback>();

  requestAnimationFrame = (cb: FrameRequestCallback): number => {
    const id = this.nextId++;
    this.pending.set(id, cb);
    return id;
  };

  cancelAnimationFrame = (id: number): void => {
    this.pending.delete(id);
  };

  /** Fires every currently queued frame once. A tick that reschedules itself
   *  (the normal case) shows up as a new pending entry for the NEXT flush. */
  flush(): void {
    const entries = [...this.pending.entries()];
    this.pending.clear();
    for (const [, cb] of entries) cb(0);
  }

  get pendingCount(): number {
    return this.pending.size;
  }
}

let raf: FakeRaf;
let getUserMedia: ReturnType<typeof vi.fn>;
let vibrateSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  raf = new FakeRaf();
  getUserMedia = vi.fn().mockResolvedValue(new FakeMediaStream());
  vibrateSpy = vi.fn();
  FakeMediaRecorder.instances = [];
  FakeAudioContext.instances = [];

  vi.stubGlobal("navigator", {
    mediaDevices: { getUserMedia },
    vibrate: vibrateSpy,
  });
  vi.stubGlobal("window", {
    setTimeout: (...args: Parameters<typeof setTimeout>) => setTimeout(...args),
    clearTimeout: (...args: Parameters<typeof clearTimeout>) => clearTimeout(...args),
    requestAnimationFrame: raf.requestAnimationFrame,
    cancelAnimationFrame: raf.cancelAnimationFrame,
  });

  vi.spyOn(voiceApi, "stt").mockResolvedValue({ text: "hello world", language_code: "en" });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function stubSupportedBrowser(): void {
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal("AudioContext", FakeAudioContext);
}

/** Drives one monitor() tick with amplitude above SPEECH_RMS (0.025), flipping
 *  the composable's private `speechStarted` flag true - the only way to reach
 *  it, since it's never exposed directly. */
function simulateLoudFrame(): void {
  const analyser = FakeAudioContext.instances.at(-1)?.analyser;
  analyser?.setAmplitude(0.1);
  raf.flush();
}

describe("start - unsupported/denied", () => {
  it('sets an error and never requests the mic when getUserMedia is missing', async () => {
    vi.stubGlobal("navigator", { mediaDevices: {}, vibrate: vibrateSpy });
    stubSupportedBrowser();
    const { start, error, state } = useInteractiveVoice(vi.fn());

    await start();

    expect(error.value).toBe("Voice input is not supported in this browser.");
    expect(state.value).toBe("idle");
  });

  it("sets an error when MediaRecorder does not exist", async () => {
    // Deliberately do NOT call stubSupportedBrowser() - MediaRecorder stays
    // undefined, matching an unsupported browser.
    const { start, error } = useInteractiveVoice(vi.fn());

    await start();

    expect(error.value).toBe("Voice input is not supported in this browser.");
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("sets a permission-denied error when getUserMedia rejects", async () => {
    stubSupportedBrowser();
    getUserMedia.mockRejectedValue(new Error("NotAllowedError"));
    const { start, error, state } = useInteractiveVoice(vi.fn());

    await start();

    expect(error.value).toBe("Microphone permission denied.");
    expect(state.value).toBe("idle");
  });
});

describe("start - success", () => {
  it("transitions to listening, vibrates, and starts recording", async () => {
    stubSupportedBrowser();
    const { start, state } = useInteractiveVoice(vi.fn());

    await start();

    expect(state.value).toBe("listening");
    expect(vibrateSpy).toHaveBeenCalledWith(50);
    expect(FakeMediaRecorder.instances.at(-1)?.state).toBe("recording");
  });

  it("clears any previous error on a new start() call", async () => {
    stubSupportedBrowser();
    getUserMedia.mockRejectedValueOnce(new Error("denied"));
    const { start, error } = useInteractiveVoice(vi.fn());
    await start();
    expect(error.value).toBe("Microphone permission denied.");

    await start();

    expect(error.value).toBeNull();
  });
});

describe("toggleMute", () => {
  it("mutes and returns to idle when muting while listening with no speech detected yet", async () => {
    stubSupportedBrowser();
    const { start, toggleMute, muted, state } = useInteractiveVoice(vi.fn());
    await start();

    toggleMute();

    expect(muted.value).toBe(true);
    expect(state.value).toBe("idle");
  });

  it("unmuting from idle resumes listening", async () => {
    stubSupportedBrowser();
    const { start, toggleMute, state } = useInteractiveVoice(vi.fn());
    await start();
    toggleMute();
    expect(state.value).toBe("idle");

    toggleMute();

    expect(state.value).toBe("listening");
  });

  it("muting while speech was already detected finalizes and transcribes instead of discarding", async () => {
    stubSupportedBrowser();
    const onUtterance = vi.fn();
    const { start, toggleMute } = useInteractiveVoice(onUtterance);
    await start();

    const recorder = FakeMediaRecorder.instances.at(-1)!;
    recorder.emitChunk();
    simulateLoudFrame();

    toggleMute();
    await vi.waitFor(() => expect(onUtterance).toHaveBeenCalled());

    expect(onUtterance).toHaveBeenCalledWith("hello world");
  });
});

describe("stopListening", () => {
  it("stops an active recorder without triggering transcription", async () => {
    stubSupportedBrowser();
    const onUtterance = vi.fn();
    const { start, stopListening } = useInteractiveVoice(onUtterance);
    await start();
    const recorder = FakeMediaRecorder.instances.at(-1)!;
    recorder.emitChunk();

    stopListening();

    expect(recorder.state).toBe("inactive");
    expect(onUtterance).not.toHaveBeenCalled();
  });

  it("does nothing when nothing is recording", () => {
    const { stopListening } = useInteractiveVoice(vi.fn());

    expect(() => stopListening()).not.toThrow();
  });
});

describe("bargeIn", () => {
  it("resumes listening on the existing stream without requesting the mic again", async () => {
    stubSupportedBrowser();
    const { start, toggleMute, bargeIn, state } = useInteractiveVoice(vi.fn());
    await start();
    toggleMute();
    getUserMedia.mockClear();

    bargeIn();

    expect(getUserMedia).not.toHaveBeenCalled();
    expect(state.value).toBe("listening");
  });

  it("requests the mic via start() when there is no existing stream", async () => {
    stubSupportedBrowser();
    const { bargeIn } = useInteractiveVoice(vi.fn());

    bargeIn();
    await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
  });
});

describe("teardown", () => {
  it("stops media tracks, closes the audio context, and resets to idle", async () => {
    stubSupportedBrowser();
    const { start, teardown, state } = useInteractiveVoice(vi.fn());
    await start();

    teardown();

    expect(state.value).toBe("idle");
  });
});

describe("transcription pipeline", () => {
  it("cleans bracketed noise and ignores it when nothing meaningful remains, then keeps listening", async () => {
    stubSupportedBrowser();
    vi.mocked(voiceApi.stt).mockResolvedValue({ text: "(laughs) [music]", language_code: "en" });
    const onUtterance = vi.fn();
    const { start, toggleMute, state } = useInteractiveVoice(onUtterance);
    await start();
    const recorder = FakeMediaRecorder.instances.at(-1)!;
    recorder.emitChunk();
    simulateLoudFrame();

    toggleMute(); // mute mid-speech -> finalizes -> transcribe
    toggleMute(); // immediately unmute so "keep listening" has somewhere to go
    await vi.waitFor(() => expect(voiceApi.stt).toHaveBeenCalled());

    expect(onUtterance).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(state.value).toBe("listening"));
  });

  it("sets a transcription-failed error and keeps listening when stt rejects", async () => {
    stubSupportedBrowser();
    vi.mocked(voiceApi.stt).mockRejectedValue(new Error("network error"));
    const onUtterance = vi.fn();
    const { start, toggleMute, error, state } = useInteractiveVoice(onUtterance);
    await start();
    const recorder = FakeMediaRecorder.instances.at(-1)!;
    recorder.emitChunk();
    simulateLoudFrame();

    toggleMute();
    toggleMute();
    await vi.waitFor(() => expect(error.value).toBe("Transcription failed."));

    expect(onUtterance).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(state.value).toBe("listening"));
  });
});
