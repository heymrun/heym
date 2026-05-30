import { ref, type Ref } from "vue";

import { voiceApi } from "@/services/api";

export type VoiceState = "idle" | "listening" | "transcribing" | "thinking" | "speaking";

const SILENCE_MS = 1200;
const SPEECH_RMS = 0.025;

interface UseInteractiveVoice {
  state: Ref<VoiceState>;
  muted: Ref<boolean>;
  error: Ref<string | null>;
  level: Ref<number>;
  start: () => Promise<void>;
  stopListening: () => void;
  toggleMute: () => void;
  setState: (s: VoiceState) => void;
  teardown: () => void;
}

// Strip ElevenLabs audio-event tags and bracketed noise, e.g. "(şıh sesi)",
// "(laughs)", "[music]", that should not be sent as a chat message.
function cleanTranscript(raw: string): string {
  return raw
    .replace(/\([^)]*\)/g, " ")
    .replace(/\[[^\]]*\]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isMeaningful(text: string): boolean {
  return text.length >= 2 && /[\p{L}\p{N}]/u.test(text);
}

export function useInteractiveVoice(onUtterance: (text: string) => void): UseInteractiveVoice {
  const state = ref<VoiceState>("idle");
  const muted = ref(false);
  const error = ref<string | null>(null);
  const level = ref(0);

  let stream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let recorder: MediaRecorder | null = null;
  let chunks: Blob[] = [];
  let rafId: number | null = null;
  let silenceTimer: number | null = null;
  let speechStarted = false;

  function setState(s: VoiceState): void {
    state.value = s;
  }

  function rms(buffer: Float32Array): number {
    let sum = 0;
    for (let i = 0; i < buffer.length; i += 1) sum += buffer[i] * buffer[i];
    return Math.sqrt(sum / buffer.length);
  }

  function beginRecording(): void {
    if (!stream) return;
    chunks = [];
    speechStarted = false;
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e): void => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = (): void => {
      const blob = new Blob(chunks, { type: recorder?.mimeType || "audio/webm" });
      if (speechStarted && blob.size > 0) {
        void transcribe(blob);
      } else if (!muted.value) {
        beginRecording();
        monitor();
      }
    };
    recorder.start();
  }

  async function transcribe(blob: Blob): Promise<void> {
    setState("transcribing");
    try {
      const result = await voiceApi.stt(blob);
      const text = cleanTranscript(result.text);
      if (isMeaningful(text)) {
        onUtterance(text);
      } else if (!muted.value) {
        // Nothing meaningful was said (silence or noise); keep listening.
        listen();
      }
    } catch {
      error.value = "Transcription failed.";
      if (!muted.value) listen();
    }
  }

  function monitor(): void {
    if (!analyser) return;
    const data = new Float32Array(analyser.fftSize);
    const tick = (): void => {
      if (!analyser || muted.value || recorder?.state !== "recording") {
        level.value = 0;
        return;
      }
      analyser.getFloatTimeDomainData(data);
      const rmsValue = rms(data);
      // Smoothed 0..1 level for the orb animation (speech rms is ~0.02-0.1).
      level.value = level.value * 0.6 + Math.min(1, rmsValue * 6) * 0.4;
      if (rmsValue > SPEECH_RMS) {
        speechStarted = true;
        if (silenceTimer) {
          window.clearTimeout(silenceTimer);
          silenceTimer = null;
        }
      } else if (speechStarted && silenceTimer === null) {
        silenceTimer = window.setTimeout(() => {
          if (recorder?.state === "recording") recorder.stop();
        }, SILENCE_MS);
      }
      rafId = window.requestAnimationFrame(tick);
    };
    rafId = window.requestAnimationFrame(tick);
  }

  function listen(): void {
    if (muted.value) return;
    setState("listening");
    beginRecording();
    monitor();
  }

  async function start(): Promise<void> {
    error.value = null;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      error.value = "Voice input is not supported in this browser.";
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      error.value = "Microphone permission denied.";
      return;
    }
    audioCtx = new AudioContext();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    listen();
  }

  function stopListening(): void {
    if (silenceTimer) {
      window.clearTimeout(silenceTimer);
      silenceTimer = null;
    }
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    level.value = 0;
    if (recorder?.state === "recording") {
      recorder.onstop = null;
      recorder.stop();
    }
  }

  function toggleMute(): void {
    muted.value = !muted.value;
    if (muted.value) {
      stopListening();
      setState("idle");
    } else {
      listen();
    }
  }

  function teardown(): void {
    stopListening();
    stream?.getTracks().forEach((t) => t.stop());
    void audioCtx?.close();
    stream = null;
    audioCtx = null;
    analyser = null;
    recorder = null;
    setState("idle");
  }

  return { state, muted, error, level, start, stopListening, toggleMute, setState, teardown };
}
